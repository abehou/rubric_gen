import json
import re
import os

trajectory_path = "/Users/bohanhou/projects/rubric_gen/runs/biomnibench-agents/all-gemini-20260705-185054/tasks/da-12-4/trajectory.stream.jsonl"

def inspect_assistant_messages():
    print("--- Inspecting Assistant Messages ---")
    with open(trajectory_path, 'r') as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "message" and event.get("role") == "assistant":
                    print(f"Message {idx}: {event.get('content')}")
                elif event.get("type") == "tool_use" and event.get("tool_name") == "update_topic":
                    print(f"Topic {idx}: {event.get('parameters')}")
            except Exception as e:
                print(f"Error parsing line {idx}: {e}")

if __name__ == "__main__":
    inspect_assistant_messages()
