# -*- coding: utf-8 -*-
# Import Libraries
import requests
import re
import json
from todoist_api_python.api import TodoistAPI
from requests.auth import HTTPDigestAuth
from datetime import datetime, timezone, timedelta
import time
from random import randint

# Load configuration files and creates a list of course_ids
config = {}
header = {}
param = {"per_page": "100", "include": "submission", "enrollment_state": "active"}
course_ids = []
assignments = []
todoist_tasks = []
courses_id_name_dict = {}
todoist_section_dict = {}
throttle_number = 50  # Number of requests to make before sleeping for delay seconds
sleep_delay_max = 2500  # Maximum number of milliseconds to sleep for
max_added = 250  # Maximum number of assignments to add to Todoist at once. Todoist API limit is 450 requests per 15 minutes and you can quickly hit this if adding a massive number of assignments.
limit_reached = False  # Global var used to terminate early if limit is reached or API returns an error.


def main():
    print(f"  {'#'*52}")
    print(" #     Canvas-Assignments-Transfer-For-Todoist     #")
    print(f"{'#'*52}\n")
    initialize_api()
    print("API INITIALIZED")
    select_courses()
    print(f"Selected {len(course_ids)} courses")
    print("Syncing Canvas Assignments...")
    load_todoist_sections()
    load_assignments()
    load_todoist_tasks()
    create_todoist_section()
    transfer_assignments_to_todoist()
    canvas_assignment_stats()
    print("Done!")


# Function for Yes/No response prompts during setup
def yes_no(question: str) -> bool:
    reply = None
    while reply not in ("y", "n"):
        reply = input(f"{question} (y/n): ").lower()
    return reply == "y"


# Makes sure that the user has their api keys and canvas url in the config.json
def initialize_api():
    global config
    global todoist_api

    try:
        with open("config.json") as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        print("File not Found, Please ensure it exists")
        initial_config()

    # create todoist_api object globally
    todoist_api = TodoistAPI(config["todoist_api_key"].strip())
    header.update({"Authorization": f"Bearer {config['canvas_api_key'].strip()}"})
    todoist_project_id = config["todoist_project_ids"].strip()




def select_courses():
    global config

    try:
        response = requests.get(
            f"{config['canvas_api_heading']}/api/v1/courses",
            headers=header,
            params=param,
        )
        if response.status_code == 401:
            print("Unauthorized; Check API Key")
            exit()
        # Note that only courses in "Active" state are returned
        if config["courses"]:
            if 1 == 1:
                course_ids.extend(
                    list(map(lambda course_id: int(course_id), config["courses"]))
                )
                for course in response.json():
                    courses_id_name_dict[course.get("id", None)] = re.sub(
                        r"[^-a-zA-Z0-9._\s]", "", course.get("name", "")
                    )
                return
    except Exception as error:
        print(f"Error while loading courses: {error}")
        print(f"Check API Key and Canvas URL")
        exit()

    # If the user does not choose to use courses selected last time
    for i, course in enumerate(response.json(), start=1):
        courses_id_name_dict[course.get("id", None)] = re.sub(
            r"[^-a-zA-Z0-9._\s]", "", course.get("name", "")
        )
        if course.get("name") is not None:
            print(
                f"{str(i)} ) {courses_id_name_dict[course.get('id', '')]} : {str(course.get('id', ''))}"
            )

    print(
        "\nEnter the courses you would like to add to Todoist by entering the numbers of the items you would like to select. Separate numbers with spaces."
    )
    my_input = input(">")
    input_array = my_input.split()
    course_ids.extend(
        list(
            map(
                lambda item: response.json()[int(item) - 1].get("id", None), input_array
            )
        )
    )

    # write course ids to config.json
    config["courses"] = course_ids
    with open("config.json", "w") as outfile:
        json.dump(config, outfile)


# Iterates over the course_ids list and loads all of the users assignments
# for those classes. Appends assignment objects to assignments list
def load_assignments():
    try:
        for course_id in course_ids:
            response = requests.get(
                f"{config['canvas_api_heading']}/api/v1/courses/{str(course_id)}/assignments",
                headers=header,
                params=param,
            )
            if response.status_code == 401:
                print("Unauthorized; Check API Key")
                exit()
            paginated = response.json()
            while "next" in response.links:
                sleep()  # Throttle requests to Canvas API to prevent rate limiting on multiple pages
                response = requests.get(
                    response.links["next"]["url"], headers=header, params=param
                )
                paginated.extend(response.json())
            print(
                f"Loaded {len(paginated)} Assignments for Course {courses_id_name_dict[course_id]}"
            )
            assignments.extend(paginated)
        print(f"Loaded {len(assignments)} Total Canvas Assignments")
        return
    except Exception as error:
        print(f"Error while loading Assignments: {error}")
        print(f"Check or regenerate API Key and Canvas URL")
        exit()


# Loads all user tasks from Todoist
def load_todoist_tasks():
    tasks = todoist_api.get_tasks()
    todoist_tasks.extend(tasks)
    print(f"Loaded {len(todoist_tasks)} Todoist Tasks")



def load_todoist_sections():
    sections = todoist_api.get_sections()
    for section in sections:
        todoist_section_dict[section.name] = section.id
        print(f"Loaded {section.name}")


def create_todoist_section():
    for course_id in course_ids:
        if courses_id_name_dict[course_id] not in todoist_section_dict:
            section = todoist_api.add_section(name=courses_id_name_dict[course_id],project_id="2341695199")
            print(f"Section {courses_id_name_dict[course_id]} created")
            todoist_section_dict[section.name] = section.id
        else:
            print(f"Section {courses_id_name_dict[course_id]} exists")
#

# Transfers over assignments from canvas over to Todoist, the method Checks
# to make sure the assignment has not already been transferred to prevent overlap
def transfer_assignments_to_todoist():
    new_added = 0
    updated = 0
    already_synced = 0
    excluded = 0
    global limit_reached
    global throttle_number
    request_count = 0
    for assignment in assignments:
        course_name = courses_id_name_dict[assignment["course_id"]]
        project_id = 2341695199
        # section_id =

        is_added = False
        is_synced = True

        for task in todoist_tasks:
            # Check if assignment is already added to Todoist with same name and within the same Project
            if (
                task.content == f"[{assignment['name']}]({assignment['html_url']}) Due"
                and task.project_id == project_id
            ):
                is_added = True
                # Ignore updates if assignment has no due date and already synced
                if assignment["due_at"] is None:
                    break
                # Handle case where task does not have due date but assignment does
                if task.due is None and assignment["due_at"] is not None:
                    is_synced = False
                    print(
                        f"Updating assignment due date: {course_name}:{assignment['name']} to {str(assignment['due_at'])}"
                    )
                    update_task(assignment, task)
                    request_count += 1
                    break
                # Check for existence of task.due first to prevent error
                if task.due is not None:
                    # Handle case where assignment and task both have due dates but they are different
                    if assignment["due_at"] != task.due.datetime:
                        is_synced = False
                        print(
                            f"Updating assignment due date: {course_name}:{assignment['name']} to {str(assignment['due_at'])}"
                        )
                        update_task(assignment, task)
                        request_count += 1
                        break

            # Handle case where assignment is not graded
            if config["sync_null_assignments"] == False:
                ## This is hacky, but it works for now - need to fix this
                if (
                    assignment["submission_types"][0] == "not_graded"
                    or assignment["submission_types"][0] == "none"
                    or assignment["submission_types"][0] == "on_paper"
                ):
                    print(
                        f"Excluding ungraded/non-submittable assignment: {course_name}: {assignment['name']}"
                    )
                    is_added = True
                    excluded += 1
                    break
            # Handle case where assignment has no due date and user has specified to not sync assignments with no due date
            if (
                assignment["due_at"] is None
                and config["sync_no_due_date_assignments"] == False
            ):
                print(
                    f"Excluding assignment with no due date: {course_name}: {assignment['name']}"
                )
                excluded += 1
                is_added = True
                break
            # Handle case where assignment is locked and unlock date is more than 2 days in the future
            if (
                assignment["unlock_at"] is not None
                and config["sync_locked_assignments"] == False
                and assignment["unlock_at"]
                > (datetime.now() + timedelta(days=3)).isoformat()
            ):
                print(
                    f"Excluding assignment that is not yet unlocked: {course_name}: {assignment['name']}: {assignment['lock_explanation']}"
                )
                is_added = True
                excluded += 1
                break
            # Handle case where assignment is locked and unlock date is empty
            if (
                assignment["locked_for_user"] == True
                and assignment["unlock_at"] is None
                and config["sync_locked_assignments"] == False
            ):
                print(
                    f"Excluding assignment that is locked: {course_name}: {assignment['name']}: {assignment['lock_explanation']}"
                )
                is_added = True
                excluded += 1
                break
        # Add assignment to Todoist if not already added - Ignore assignments that are already submitted
        if not is_added:
            if assignment["submission"]["workflow_state"] == "unsubmitted":
                print(f"Adding assignment {course_name}: {assignment['name']}")
                add_new_task(assignment, project_id)
                new_added += 1
                request_count += 1
        # Update count of updated assignments (updated due date - already updated in Todoist)
        if is_added and not is_synced:
            updated += 1
        # Update count of already synced assignments (already synced to Todoist, no updates)
        if is_synced and is_added:
            already_synced += 1
        if new_added > max_added:
            limit_reached = True
        if limit_reached:
            break
        # Throttle requests to Todoist API to prevent rate limiting, sleep every 50 requests
        if request_count % throttle_number == 0 and request_count > 1:
            print(f"Current request count: {request_count}")
            sleep()
    if limit_reached:
        print(
            f"Reached Todoist API or configured limit. Not all tasks added. Please try again in 15 minutes."
        )
    print(f"  {'-'*52}")
    print(f"Added to Todoist: {new_added}")
    print(f"Due Date Updated In Todoist: {updated}")
    print(f"Already Synced to Todoist: {already_synced}")
    print(f"Excluded: {excluded}")


# Adds a new task from a Canvas assignment object to Todoist under the
# project corresponding to project_id
def add_new_task(assignment, todoist_project_id):
    course_name = courses_id_name_dict[assignment["course_id"]]
    global limit_reached
    try:
        todoist_api.add_task(
            content="["
            + assignment["name"]
            + "]("
            + assignment["html_url"]
            + ")"
            + " Due",
            project_id=todoist_project_id,
            due_datetime=assignment["due_at"],
            labels=config["todoist_task_labels"],
            priority=config["todoist_task_priority"],
            section_id= todoist_section_dict[course_name]
        )
    except Exception as error:
        print(
            f"Error while adding task: {error}, likely due to rate limiting. Try again in 15 minutes"
        )
        limit_reached = True


def canvas_assignment_stats():
    print(f"  {'-'*52}")
    print(" #     Current Canvas Assignment Statistics     #")
    print(f"Total Assignments: {len(assignments)}")
    graded_timestamps = []
    submitted = 0
    ignored_not_graded = 0
    ignored_no_submission = 0
    locked = 0
    instructor_graded = 0
    for assignment in assignments:
        # Check for assignment graded_at dates, and if graded_at is not None, add to graded_timestamps list to report most recent grade update
        if assignment["submission"]["graded_at"] is not None:
            timestamp = datetime.strptime(
                (assignment["submission"]["graded_at"]), "%Y-%m-%dT%H:%M:%SZ"
            )
            graded_timestamps.append(timestamp)
        if assignment["graded_submissions_exist"] == True:
            instructor_graded += 1
        if assignment["submission"]["workflow_state"] != "unsubmitted":
            submitted += 1
        elif assignment["locked_for_user"] == True:
            locked += 1
        elif assignment["submission_types"][0] == "none":
            ignored_no_submission += 1
        elif assignment["submission_types"][0] == "not_graded":
            ignored_not_graded += 1

    print(f"Total Submitted: {submitted}")
    print(f"Total Locked: {locked}")
    print(f"Total Unsubmittable: {ignored_no_submission}")
    print(f"Total Not_Graded: {ignored_not_graded}")
    print(
        f"Remaining (unlocked) Assignments: {(len(assignments)-submitted-ignored_not_graded-ignored_no_submission-locked)}"
    )
    print(f"\n Grading Statistics:")
    print(f"Total Currently Graded: {max(instructor_graded,len(graded_timestamps))}")
    latest_update = max(graded_timestamps, default=0)
    if latest_update == 0:
        print(f"Last Grade Update: Never")
    else:
        print(f"Last Grade Update: {aslocaltimestr(latest_update)}")


def update_task(assignment, task):
    global limit_reached
    try:
        todoist_api.update_task(task_id=task.id, due_datetime=assignment["due_at"])
    except Exception as error:
        print(f"Error while updating task: {error}")
        limit_reached = True


# Credit to https://stackoverflow.com/questions/4563272/how-to-convert-a-utc-datetime-to-a-local-datetime-using-only-standard-library
# This funciton is simply used for printing out graded and due dates in local time. It is not used for the task creation, as tasks MUST be created in UTC
def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)


def aslocaltimestr(utc_dt):
    return utc_to_local(utc_dt).strftime("%Y-%m-%d %I:%M%p")


# Function for throttling/sleeping
def sleep():
    delay = (
        randint(100, sleep_delay_max) / 1000
    )  # random delay for throttling/rate limiting
    print(f"Sleeping for {delay} seconds...")
    time.sleep(delay)


if __name__ == "__main__":
    main()
