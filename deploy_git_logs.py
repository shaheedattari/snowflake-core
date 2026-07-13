import os
import subprocess
import snowflake.connector
from datetime import datetime

# ----------------------------------
# Connect to Snowflake
# ----------------------------------

print("Connecting to Snowflake...")

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
    role=os.environ["SNOWFLAKE_ROLE"]
)

cur = conn.cursor()

deploy_id = None

try:

    # ----------------------------------
    # Target Database comes from workflow
    # develop -> FIRST_TECH_DCU_D
    # main    -> FIRST_TECH_DCU_U
    # ----------------------------------

    target_db = os.environ["TARGET_DATABASE"]

    print(f"Deploying to {target_db}")

    cur.execute(f"USE DATABASE {target_db}")
    cur.execute("USE SCHEMA BRONZE")

    # ----------------------------------
    # GitHub Information
    # ----------------------------------

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
    # Get Deployment ID
    #########################################################

    cur.execute("SELECT MAX(DEPLOY_ID) FROM DEPLOYMENT_HISTORY")
    deploy_id = cur.fetchone()[0]

    print(f"Deployment ID : {deploy_id}")
   

    # ----------------------------------
    # Get Changed Files
    # ----------------------------------

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

    # ----------------------------------
    # Filter SQL Files
    # ----------------------------------

    sql_files = [
        f for f in changed_files
        if f.endswith(".sql")
    ]

    print("Changed SQL files:")

    for file_name in sql_files:
        print(file_name)

    # ----------------------------------
    # No SQL Changes
    # ----------------------------------

    if len(sql_files) == 0:
        print("No SQL files change(s) found updating status as NO_CHANGE")

        cur.execute("""
        UPDATE DEPLOYMENT_HISTORY
        SET STATUS='NO_CHANGE',
            END_TIME=CURRENT_TIMESTAMP(),
            FILES_DEPLOYED=0
        WHERE DEPLOY_ID=%s
        """,
        (deploy_id,)
        )
        print("No SQL files found for deployment updated status as NO_CHANGE.")
        exit(0)

    # ----------------------------------
    # Execute SQL Files
    # ----------------------------------

    for file_name in sql_files:

        print(f"Executing : {file_name}")

        with open(file_name, "r", encoding="utf-8") as f:
            sql_script = f.read()
        #additional check
        if not sql_script.strip():
            print(f"Skipping Empty File : {file_name}")
            continue

        cur.execute(
            sql_script,
            num_statements=0
        )

        print(f"Completed : {file_name}")

    # ----------------------------------
    # Deployment Successful
    # ----------------------------------
    print("SQL files change(s) found updating status as SUCCESS")
    cur.execute("""
    UPDATE DEPLOYMENT_HISTORY
    SET STATUS='SUCCESS',
        END_TIME=CURRENT_TIMESTAMP(),
        FILES_DEPLOYED=%s
    WHERE DEPLOY_ID=%s
    """,
    (
        len(sql_files),
        deploy_id
    ))

    print("Deployment Successful updated status as SUCCESS")

except Exception as e:

    print(f"Deployment failed: {e}")

    if deploy_id is not None:

        try:
            print("Issue in deployment, updating status as FAILED")

            cur.execute("""
                UPDATE DEPLOYMENT_HISTORY
                SET STATUS = 'FAILED',
                    END_TIME = CURRENT_TIMESTAMP(),
                    ERROR_MESSAGE = %s
                WHERE DEPLOY_ID = %s
            """,
            (
                str(e),
                deploy_id
            ))

            print("Issue in deployment, updated status as FAILED")

        except Exception as update_error:
            print(f"Failed to update deployment history: {update_error}")

    raise

finally:

    cur.close()
    conn.close()

    print("Snowflake Connection Closed")
