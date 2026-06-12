# tools/memory_manager.py

import os
import json
from pathlib import Path

# Unifying the location into your active workspace directory
MEMORY_FILE_PATH = Path("/usr/local/google/home/bmajumdar/Documents/GH-PR/github-PR/.memory_store.json")

class ADKMemoryService:
    @staticmethod
    def store_memory(memory_entry: dict):
        database = []
        if MEMORY_FILE_PATH.exists():
            try:
                with open(MEMORY_FILE_PATH, 'r') as f:
                    database = json.load(f)
            except json.JSONDecodeError:
                database = []

        existing_ids = {item.get("comment_id") for item in database if "comment_id" in item}
        if memory_entry.get("comment_id") not in existing_ids:
            database.append(memory_entry)
            with open(MEMORY_FILE_PATH, 'w') as f:
                json.dump(database, f, indent=2)
            return f"Stored constraint successfully: {memory_entry.get('identified_error')}"
        return "Constraint already registered in memory bank."

    @staticmethod
    def retrieve_relevant_constraints(target_file_path: str) -> list:
        if not MEMORY_FILE_PATH.exists():
            return []

        try:
            with open(MEMORY_FILE_PATH, 'r') as f:
                database = json.load(f)
        except Exception:
            return []

        matched_constraints = []
        for entry in database:
            affected = entry.get("affected_file", "")
            if affected == "global" or affected in target_file_path or target_file_path in affected:
                matched_constraints.append(entry)
        return matched_constraints

def persist_feedback_to_memory(feedback_json_str: str) -> str:
    try:
        feedback_list = json.loads(feedback_json_str)
        stored_count = 0
        for item in feedback_list:
            res = ADKMemoryService.store_memory(item)
            if "successfully" in res:
                stored_count += 1
        return f"Successfully imported {stored_count} new constraints into long-term memory."
    except Exception as e:
        return f"Failed to ingest feedback: {str(e)}"

def retrieve_negative_constraints(target_file: str) -> str:
    constraints = ADKMemoryService.retrieve_relevant_constraints(target_file)
    if not constraints:
        return "No historical negative constraints found for this scope."
    return json.dumps(constraints, indent=2)