import os
import subprocess
import snowflake.connector

print("Connecting to Snowflake...")

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
    role=os.environ["SNOWFLAKE_ROLE"]
)

cur = conn.cursor()

try:

    target_db = os.environ["TARGET_DATABASE"]

    print(f"Deploying to {target_db}")

    cur.execute(f"USE DATABASE {target_db}")
    cur.execute("USE SCHEMA GITHUB")

    # Get all tags sorted descending
    tags = subprocess.check_output(
        ["git", "tag", "--sort=-version:refname"]
    ).decode().splitlines()

    print(f"Available tags: {tags}")

    # First release
    if len(tags) < 2:

        print("First release detected.")
        print("Deploying all SQL files.")

        changed_files = subprocess.check_output(
            ["git", "ls-files"]
        ).decode().splitlines()

    else:

        current_tag = tags[0]
        previous_tag = tags[1]

        print(f"Comparing {previous_tag} -> {current_tag}")

        changed_files = subprocess.check_output(
            [
                "git",
                "diff",
                "--name-only",
                previous_tag,
                current_tag
            ]
        ).decode().splitlines()

    # Only SQL files
    sql_files = [
        f for f in changed_files
        if f.endswith(".sql")
    ]

    print("Files selected for deployment:")

    for file_name in sql_files:
        print(file_name)

    if len(sql_files) == 0:
        print("No SQL files changed.")
        exit(0)

    # Execute files
    for file_name in sql_files:

        print(f"Executing: {file_name}")

        with open(file_name, "r", encoding="utf-8") as f:
            sql_script = f.read()

        # Skip empty files
        if len(sql_script.strip()) == 0:
            print(f"Skipping empty file: {file_name}")
            continue

        cur.execute(sql_script)

        print(f"Completed: {file_name}")

    print("Deployment Successful!")

finally:

    cur.close()
    conn.close()

    print("Snowflake connection closed.")
