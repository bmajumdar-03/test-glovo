# tools/github_pr_tool.py

import os
import time
import subprocess
import webbrowser
from enum import Enum
from dotenv import load_dotenv
from github import Github, GithubException, Auth

load_dotenv("/usr/local/google/home/bmajumdar/Documents/GH-PR/github-PR/.env")

class PRState(Enum):
    INIT = "INIT"
    FETCH_SECRET = "FETCH_SECRET"
    CHECK_BRANCH = "CHECK_BRANCH"
    HANDLE_CONFLICT = "HANDLE_CONFLICT"
    COMMIT_CODE = "COMMIT_CODE"
    OPEN_PR = "OPEN_PR"
    APPLY_TAGS = "APPLY_TAGS"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"

class GitHubPRStateMachine:
    def __init__(self, commit_message: str, target_directory: str = None, auto_detect: bool = True):
        self.project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID")
        self.secret_id = os.getenv("SECRET_ID")
        self.secret_version = os.getenv("SECRET_VERSION", "latest")
        self.repo_name = os.getenv("GITHUB_REPO")
        
        raw_prefix = os.getenv("GITHUB_BRANCH_PREFIX", "")
        self.branch_prefix = raw_prefix.strip() if raw_prefix.strip() else "sql-migration"
        
        raw_labels = os.getenv("GITHUB_PR_LABELS", "caretta-automated")
        self.labels = [label.strip() for label in raw_labels.split(",") if label.strip()]

        self.base_branch = "main"
        
        timestamp = int(time.time())
        self.target_branch = f"{self.branch_prefix}-{timestamp}"
        
        self.commit_message = commit_message
        self.target_directory = target_directory
        self.auto_detect = auto_detect
        
        self.files_to_commit = {}  # Map of repo path -> text content
        self.state = PRState.INIT
        self.token = None
        self.repo = None
        self.pr = None  
        self.error_msg = ""

        # Programmatic protection list to ensure runtime tools are never committed to your repository
        self.automation_exclusion_rules = [
            ".env",
            ".memory_store.json",
            "tools/",              # Exclude feedback tool, pr tool, memory manager
            "agent.py",            # Exclude direct agent executors
            "__pycache__/",
            ".git/",
            ".venv/",
            "venv/"
        ]

    def _access_secret_manager(self) -> str:
        """Retrieves GitHub token directly from local environment configurations."""
        fallback_token = os.getenv("GITHUB_TOKEN")
        if fallback_token:
            print(" > Using GITHUB_TOKEN from local environment configuration.")
            return fallback_token.strip()
            
        raise RuntimeError("Could not resolve a GITHUB_TOKEN from environment variables.")

    def _should_exclude_file(self, file_path: str) -> bool:
        """Determines if a path belongs to the automation runner system rather than target workspace code."""
        normalized_path = file_path.replace("\\", "/").strip("./")
        
        # Check against exclusion list rules
        for rule in self.automation_exclusion_rules:
            clean_rule = rule.strip("./")
            if clean_rule.endswith("/"):
                # Directory match
                if normalized_path.startswith(clean_rule) or f"/{clean_rule}" in normalized_path:
                    return True
            else:
                # File match
                if normalized_path == clean_rule or normalized_path.endswith(f"/{clean_rule}"):
                    return True
        return False

    def _get_git_status_files(self) -> list:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "-uall"],
                capture_output=True,
                text=True,
                check=True
            )
            changed_files = []
            for line in result.stdout.splitlines():
                if len(line) > 3:
                    file_path = line[3:].strip()
                    if file_path.startswith('"') and file_path.endswith('"'):
                        file_path = file_path[1:-1]
                        
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        # Filter out system orchestration files
                        if self._should_exclude_file(file_path):
                            continue
                        changed_files.append(file_path)
            return changed_files
        except Exception as e:
            print(f"⚠️ Failed to execute local git status check: {e}")
            return []

    def _collect_files(self):
        collected_paths = []
        if self.auto_detect:
            collected_paths = self._get_git_status_files()

        # Fallback to targeted directory scan if no changes were found via Git or if auto_detect is disabled
        if not collected_paths and self.target_directory and os.path.exists(self.target_directory):
            print(f" > Falling back to scanning directory: {self.target_directory}")
            
            for root, dirs, files in os.walk(self.target_directory):
                # Prune directory search trees dynamically
                dirs[:] = [d for d in dirs if not self._should_exclude_file(os.path.join(root, d))]
                for file in files:
                    full_path = os.path.join(root, file)
                    if self._should_exclude_file(full_path):
                        continue
                    collected_paths.append(full_path)

        # Map files into delivery payloads
        for path in collected_paths:
            repo_path = os.path.relpath(path, start=os.getcwd())
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.files_to_commit[repo_path] = f.read()
            except UnicodeDecodeError:
                continue
            except Exception as e:
                print(f"⚠️ Could not read {path}: {e}")

    def run(self):
        self._collect_files()

        if not self.files_to_commit:
            self.error_msg = "No files with changes detected in the workspace."
            self.state = PRState.ERROR
            return
        
        print(" > Files targeted for delivery:")
        for target in self.files_to_commit.keys():
            print(f"   - {target}")
        
        while self.state not in [PRState.SUCCESS, PRState.ERROR]:
            if self.state == PRState.INIT:
                if not self.repo_name:
                    self.error_msg = "Missing required environment configuration 'GITHUB_REPO'"
                    self.state = PRState.ERROR
                else:
                    self.state = PRState.FETCH_SECRET

            elif self.state == PRState.FETCH_SECRET:
                try:
                    self.token = self._access_secret_manager()
                    auth = Auth.Token(self.token)
                    g = Github(auth=auth)
                    self.repo = g.get_repo(self.repo_name)
                    self.state = PRState.CHECK_BRANCH
                except Exception as e:
                    self.error_msg = str(e)
                    self.state = PRState.ERROR

            elif self.state == PRState.CHECK_BRANCH:
                try:
                    base_ref = self.repo.get_git_ref(f"heads/{self.base_branch}")
                    self.repo.create_git_ref(ref=f"refs/heads/{self.target_branch}", sha=base_ref.object.sha)
                    self.state = PRState.COMMIT_CODE
                except GithubException as e:
                    if e.status == 422:  
                        self.state = PRState.HANDLE_CONFLICT
                    else:
                        self.error_msg = f"Branch creation error: {str(e)}"
                        self.state = PRState.ERROR

            elif self.state == PRState.HANDLE_CONFLICT:
                time.sleep(1) 
                timestamp = int(time.time())
                self.target_branch = f"{self.branch_prefix}-{timestamp}"
                self.state = PRState.CHECK_BRANCH

            elif self.state == PRState.COMMIT_CODE:
                try:
                    for repo_path, content in self.files_to_commit.items():
                        try:
                            try:
                                contents = self.repo.get_contents(repo_path, ref=self.target_branch)
                                self.repo.update_file(
                                    path=repo_path,
                                    message=self.commit_message,
                                    content=content,
                                    sha=contents.sha,
                                    branch=self.target_branch
                                )
                                print(f"   - Updated: {repo_path}")
                            except GithubException as e:
                                if e.status == 404:  
                                    self.repo.create_file(
                                        path=repo_path,
                                        message=self.commit_message,
                                        content=content,
                                        branch=self.target_branch
                                    )
                                    print(f"   - Created: {repo_path}")
                                else:
                                    raise e
                        except Exception as file_err:
                            print(f" ⚠️ Failed to commit {repo_path}: {str(file_err)}")
                    self.state = PRState.OPEN_PR
                except Exception as e:
                    self.error_msg = f"Code commitment sequence failed: {str(e)}"
                    self.state = PRState.ERROR

            elif self.state == PRState.OPEN_PR:
                try:
                    self.pr = self.repo.create_pull(
                        title=f"[Caretta] {self.commit_message}",
                        body="This PR contains the dynamic set of generated and modified files.",
                        head=self.target_branch,
                        base=self.base_branch
                    )
                    print(f" > Opened Pull Request successfully: {self.pr.html_url}")
                    
                    try:
                        print(f" > Launching web browser to: {self.pr.html_url}")
                        webbrowser.open(self.pr.html_url, new=2)
                    except Exception as browser_err:
                        print(f" ⚠️ Could not launch browser automatically: {str(browser_err)}")
                        
                    self.state = PRState.APPLY_TAGS
                except GithubException as e:
                    self.error_msg = f"Pull Request formulation failure: {str(e)}"
                    self.state = PRState.ERROR

            elif self.state == PRState.APPLY_TAGS:
                try:
                    if self.labels and self.pr:
                        self.pr.add_to_labels(*self.labels)
                    self.state = PRState.SUCCESS
                except GithubException as e:
                    print(f" ⚠️ Non-fatal warning: Failed to apply PR labels: {str(e)}")
                    self.state = PRState.SUCCESS

def execute_automated_pr(commit_message: str, target_directory: str = None, auto_detect: bool = True) -> str:
    machine = GitHubPRStateMachine(
        commit_message=commit_message, 
        target_directory=target_directory, 
        auto_detect=auto_detect
    )
    machine.run()
    if machine.state == PRState.SUCCESS:
        pr_url = machine.pr.html_url if machine.pr else "URL not resolved"
        return (
            f"Successfully opened PR on branch {machine.target_branch}.\n"
            f"PR Web Link: {pr_url}"
        )
    return f"Failed to execute PR workflow. Error: {machine.error_msg}"