import os
import subprocess
import snowflake.connector
from datetime import datetime


descriptor_file_path = "deploy/deployment_descriptor.txt"
sql_files1 = []
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
        git_version = subprocess.check_output(["git", "describe", "--tags", "--abbrev=0"]).decode().strip()
    except:
        git_version = "NO_TAG"

    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    git_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
    github_run_id = os.getenv("GITHUB_RUN_ID", "")
    github_workflow = os.getenv("GITHUB_WORKFLOW", "")
    github_repository = os.getenv("GITHUB_REPOSITORY", "")
    deployed_by = os.getenv("GITHUB_ACTOR", "")
    start_time = datetime.now()
        
    
    #########################################################
    # Insert RUNNING Record
    #########################################################
   
    sql_insert = "INSERT INTO DEPLOYMENT_HISTORY  (GIT_VERSION,GIT_COMMIT_ID,GIT_BRANCH,GITHUB_RUN_ID,GITHUB_WORKFLOW,GITHUB_REPOSITORY,DEPLOYED_BY,TARGET_DATABASE,START_TIME,STATUS) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    values = (git_version, git_commit, git_branch, github_run_id, github_workflow, github_repository, deployed_by, target_db, start_time, "RUNNING")
    cur.execute(sql_insert, values)
    
    #########################################################
    # Get Deployment ID
    #########################################################

    cur.execute("SELECT MAX(DEPLOY_ID) FROM DEPLOYMENT_HISTORY")
    deploy_id = cur.fetchone()[0]

    print(f"Deployment ID : {deploy_id}")
   

    # ----------------------------------
    # Get Changed Files
    # ----------------------------------

    tags = subprocess.check_output(["git", "tag", "--sort=-version:refname"]).decode().splitlines()

    print(f"Available tags: {tags}")

    if len(tags) < 2:

        print("First release detected.")
        print("Deploying all SQL files.")
        # changed_files = subprocess.check_output(["git", "ls-files"]).decode().splitlines()
        # Read deployment descriptor file to get the list of SQL files to deploy
        print(f"Reading deployment descriptor to get the list of SQL files to deploy from : {descriptor_file_path}")
        if not os.path.exists(descriptor_file_path):
            raise Exception(f"{descriptor_file_path} not found.")
        with open(descriptor_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Ignore blank lines
                if line == "":
                    continue
                # Ignore comments
                if line.startswith("#"):
                    continue
                sql_files1.append(line)

        print("\n Deployment Order")
        for i, file_name in enumerate(sql_files1, start=1):
            print(f"{i}. {file_name}")

        # ----------------------------------
        # Validate deployment files
        # ----------------------------------
        missing_files = []
        for file_name in sql_files1:
            if not os.path.exists(file_name):
                missing_files.append(file_name)
        if missing_files:
            print("\n Missing SQL Files")
            for f in missing_files:
                print(f)
            raise Exception("Deployment stopped because deployment_descriptor.txt contains missing files.")

    else:
        current_tag = tags[0]
        previous_tag = tags[1]
        print(f"Comparing {previous_tag} -> {current_tag}")
        
        # changed_files = subprocess.check_output(["git","diff","--name-only",previous_tag,current_tag]).decode().splitlines()
        # print(f"Changed files: {changed_files}")
        # Read deployment descriptor file to get the list of SQL files to deploy
        print(f"Reading deployment descriptor to get the list of SQL files to deploy from : {descriptor_file_path}")
        if not os.path.exists(descriptor_file_path):
            raise Exception(f"{descriptor_file_path} not found.")

        with open(descriptor_file_path, "r", encoding="utf-8") as f:

            for line in f:
                line = line.strip()
                # Ignore blank lines
                if line == "":
                    continue
                # Ignore comments
                if line.startswith("#"):
                    continue
                sql_files1.append(line)

        print("\n Deployment Order")
        for i, file_name in enumerate(sql_files1, start=1):
            print(f"{i}. {file_name}")

        # ----------------------------------
        # Validate deployment files
        # ----------------------------------
        missing_files = []
        for file_name in sql_files1:
            if not os.path.exists(file_name):
                missing_files.append(file_name)
        if missing_files:
            print("\n Missing SQL Files")
            for f in missing_files:
                print(f)
            raise Exception("Deployment stopped because deployment_descriptor.txt contains missing files.")
    
    # ----------------------------------
    # Filter SQL Files
    # ----------------------------------

    sql_files = [
        f for f in sql_files1
        if f.endswith(".sql")
    ]
    sql_files_list = ",".join(sql_files)
    print(f"file list : {sql_files_list}")
    print("Changed SQL files:")

    for file_name in sql_files:
        print(file_name)

    # ----------------------------------
    # No SQL Changes
    # ----------------------------------

    if len(sql_files) == 0:
        print(f"No SQL files change(s) found. Updating status as NO_CHANGE for DEPLOY_ID: {deploy_id}")
        
        sql_update = "UPDATE DEPLOYMENT_HISTORY SET STATUS = 'NO_CHANGE', END_TIME = CURRENT_TIMESTAMP(), FILE_COUNT = 0 WHERE DEPLOY_ID = %s"
        cur.execute(sql_update, (deploy_id,))
        
        print(f"No SQL files found for deployment. Updated status as NO_CHANGE for DEPLOY_ID: {deploy_id}")
        exit(0)

    # ----------------------------------
    # Execute SQL Files
    # ----------------------------------

    for file_name in sql_files:

        print(f" Started Executing : {file_name}")

        with open(file_name, "r", encoding="utf-8") as f:
            sql_script = f.read()
        #additional check
        if not sql_script.strip():
            print(f"Skipping Empty File : {file_name}")
            continue

        cur.execute(sql_script,num_statements=0)
        print(f"Completed executing : {file_name}")

    # ----------------------------------
    # Deployment Successful
    # ----------------------------------
    try:
        print(f"SQL files change(s) found updating status as SUCCESS for DEPLOY_ID: {deploy_id}")

        sql_files_list = ",".join(sql_files)
        print(f"file list : {sql_files_list}")
        print(f"sql_files : {sql_files}")
        print(f"deploy_id : {deploy_id}")
        
        sql_update = "UPDATE DEPLOYMENT_HISTORY SET STATUS='SUCCESS', END_TIME=CURRENT_TIMESTAMP(), FILE_COUNT=%s, FILES_DEPLOYED=%s WHERE DEPLOY_ID=%s"
        cur.execute(sql_update, (len(sql_files), sql_files_list, deploy_id))

        print(f"Deployment Successful updated status as SUCCESS for DEPLOY_ID: {deploy_id}")
        print("Rows affected:", cur.rowcount)
        conn.commit()
       
    except Exception as e1:
        print("Update failed:", e1)

except Exception as e:

    print(f"Deployment failed: {e}")

    if deploy_id is not None:

        try:
            print(f"Issue in deployment, updating status as FAILED for DEPLOY_ID: {deploy_id}")

            sql_update = "UPDATE DEPLOYMENT_HISTORY SET STATUS = 'FAILED', END_TIME = CURRENT_TIMESTAMP(), FILE_COUNT = 0, ERROR_MESSAGE = %s WHERE DEPLOY_ID = %s"
            cur.execute(sql_update, (str(e), deploy_id))

            print(f"Issue in deployment, updated status as FAILED for DEPLOY_ID: {deploy_id}")

        except Exception as update_error:
            print(f"Failed to update deployment history: {update_error}")

finally:

    print("In Finally block,closing Snowflake connection...")
    cur.close()
    conn.close()
    print("Snowflake Connection Closed")
