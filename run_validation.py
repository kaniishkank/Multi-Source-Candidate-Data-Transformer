import os
import json
import subprocess

# 1. Create 'data' folder if it does not exist
os.makedirs("data", exist_ok=True)
print("1. Created 'data/' directory.")

# 2. Write sample structured file to 'data/recruiter.csv'
csv_content = """name,email,phone,skills
Kaushikan,kaushikan@example.com,+1234567890,"Python, SQL"
"""
with open("data/recruiter.csv", "w", encoding="utf-8") as f:
    f.write(csv_content)
print("2. Created 'data/recruiter.csv'.")

# 3. Write sample unstructured text file to 'data/notes.txt'
notes_content = """Met with Kaushikan today. He is a software engineer currently based in Chennai, India. He mentioned his GitHub profile email is kani.dev@github.io. He has fantastic experience building data pipelines using Apache Spark and Python.
"""
with open("data/notes.txt", "w", encoding="utf-8") as f:
    f.write(notes_content)
print("3. Created 'data/notes.txt'.")

# 4. Write runtime layout specification to 'config.json'
config_content = {
  "fields": [
    {"path": "full_name", "required": True},
    {"path": "primary_email", "from": "emails[0]", "required": True},
    {"path": "skills"}
  ],
  "include_confidence": True,
  "on_missing": "null"
}
with open("config.json", "w", encoding="utf-8") as f:
    json.dump(config_content, f, indent=2)
print("4. Created 'config.json'.")

# 5. Run unittest and print output
print("\n5. Executing unit tests via subprocess...")
result = subprocess.run(["python", "-m", "unittest", "test_pipeline.py"], capture_output=True, text=True)

print("\n--- Subprocess Unit Test Output ---")
if result.stdout:
    print(f"STDOUT:\n{result.stdout}")
if result.stderr:
    print(f"STDERR:\n{result.stderr}")
print("-----------------------------------")
