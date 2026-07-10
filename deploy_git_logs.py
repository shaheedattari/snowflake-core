import os
import subprocess
import snowflake.connector
from datetime import datetime

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

    #########################################################
    # Get Git Information
    #########################################################

    try:
        git_version = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"]
        ).decode().strip()
    except:
        git_version = "NO_TAG"

    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"]
    ).decode().strip()

    git_branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    ).decode().strip()

    github_run_id = os.getenv("GITHUB_RUN_ID", "")

    github_workflow = os.getenv("GITHUB_WORKFLOW", "")

    github_repository = os.getenv("GITHUB_REPOSITORY", "")

    deployed_by = os.getenv("GITHUB_ACTOR", "")

    start_time = datetime.now()

    #########################################################
    # Insert RUNNING Record
    #########################################################

    cur.execute("""
        INSERT INTO DEPLOYMENT_HISTORY
        (
            GIT_VERSION,
            GIT_COMMIT_ID,
            GIT_BRANCH,
            GITHUB_RUN_ID,
            GITHUB_WORKFLOW,
            GITHUB_REPOSITORY,
            DEPLOYED_BY,
            TARGET_DATABASE,
            START_TIME,
            STATUS
        )
        VALUES
        (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
    """,
    (
        git_version,
        git_commit,
        git_branch,
        github_run_id,
        github_workflow,
        github_repository,
        deployed_by,
        target_db,
        start_time,
        "RUNNING"
    ))

    #########################################################
    # Get DEPLOY_ID
    #########################################################

    cur.execute("SELECT MAX(DEPLOY_ID) FROM DEPLOYMENT_HISTORY")
    deploy_id = cur.fetchone()[0]

    #########################################################
    # Existing Code
    #########################################################

    tags = subprocess.check_output(
        ["git", "tag", "--sort=-version:refname"]
    ).decode().splitlines()

    print(f"Available tags: {tags}")

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

    sql_files = [
        f for f in changed_files
        if f.endswith(".sql")
    ]

    print("Files selected for deployment:")

    for file_name in sql_files:
        print(file_name)

    if len(sql_files) == 0:
        print("No SQL files changed.")

        cur.execute("""
        UPDATE DEPLOYMENT_HISTORY
        SET STATUS='NO_CHANGE',
            END_TIME=CURRENT_TIMESTAMP,
            FILES_DEPLOYED=0
        WHERE DEPLOY_ID=%s
        """, (deploy_id,))

        exit(0)

    #########################################################
    # Execute SQL Files
    #########################################################

    for file_name in sql_files:

        print(f"Executing: {file_name}")

        with open(file_name, "r", encoding="utf-8") as f:
            sql_script = f.read()

        if len(sql_script.strip()) == 0:
            continue

        cur.execute(sql_script)

        print(f"Completed: {file_name}")

    #########################################################
    # Update SUCCESS
    #########################################################

    cur.execute("""
    UPDATE DEPLOYMENT_HISTORY
    SET STATUS='SUCCESS',
        END_TIME=CURRENT_TIMESTAMP,
        FILES_DEPLOYED=%s
    WHERE DEPLOY_ID=%s
    """,
    (
        len(sql_files),
        deploy_id
    ))

    print("Deployment Successful!")

except Exception as e:

    print(str(e))

    #########################################################
    # Update FAILED
    #########################################################

    try:
        cur.execute("""
        UPDATE DEPLOYMENT_HISTORY
        SET STATUS='FAILED',
            END_TIME=CURRENT_TIMESTAMP,
            ERROR_MESSAGE=%s
        WHERE DEPLOY_ID=%s
        """,
        (
            str(e),
            deploy_id
        ))
    except:
        pass

    raise

finally:

    cur.close()
    conn.close()

    print("Snowflake connection closed.")
