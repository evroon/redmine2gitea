import requests
import os
import json
import time
import datetime
import pytz
from dotenv import load_dotenv

load_dotenv()

REDMINE_DOMAIN = os.getenv('REDMINE_DOMAIN')
REDMINE_API_TOKEN = os.getenv('REDMINE_API_TOKEN')
REDMINE_PROJECT_NAME = os.getenv('REDMINE_PROJECT_NAME')
REDMINE_HEADERS = {
    'accept': 'application/json',
    'X-Redmine-API-Key': REDMINE_API_TOKEN,
    'Content-Type': 'application/json',
}

GITEA_DOMAIN = os.getenv('GITEA_DOMAIN')
GITEA_API_TOKEN = os.getenv('GITEA_API_TOKEN')
GITEA_REPO = os.getenv('GITEA_REPO')
GITEA_ENDPOINT = f'api/v1/repos/{GITEA_REPO}/issues'
GITEA_HEADERS = {
    'accept': 'application/json',
    'Authorization': f'token {GITEA_API_TOKEN}',
    'Content-Type': 'application/json',
}

DEFAULT_USERNAME = os.getenv('DEFAULT_USERNAME')


def process_issues() -> None:
    issues = get_issues()
    labels = get_labels()
    projects = get_projects()
    users = get_users()

    for issue in issues:
        create_issue(issue, labels, projects, users)


def get_users() -> dict:
    """Returns all users as registered in Redmine.

    Returns:
        dict: Dict of (username, name) pairs for each user id
    """
    response = requests.get(f'https://{REDMINE_DOMAIN}/users.json', headers=REDMINE_HEADERS)
    result = {}

    for user in json.loads(response.content)['users']:
        result[user['id']] = {
            'username': user['login'],
            'name': user['firstname'] + ' ' + user['lastname'],
        }

    return result


def get_projects() -> dict:
    """Returns all projects as registered in Redmine.

    Returns:
        dict: Dict of project names for each id
    """
    response = requests.get(f'https://{REDMINE_DOMAIN}/projects.json', headers=REDMINE_HEADERS)
    result = {}

    for project in json.loads(response.content)['projects']:
        result[project['id']] = project['name']

    return result


def get_issues(limit: int = 10000, offset: int = 0) -> dict:
    """Get issues from the Redmine instance.

    Args:
        limit (int, optional): Limit the number of issues returned. Defaults to 10.
        offset (int, optional): Offset for pagination of issues. Defaults to 0.

    Returns:
        dict: Issues with data in key-value pairs.
    """
    response = requests.get(f'https://{REDMINE_DOMAIN}/projects/{REDMINE_PROJECT_NAME}/' +
        f'issues.json?status_id=*&limit={limit}&offset={offset}', headers=REDMINE_HEADERS)

    return json.loads(response.content)['issues']


def get_labels() -> dict:
    """Get the labels used for the repo in Gitea.

    Returns:
        dict: Pairs of (name, id) of all labels.
    """
    result = {}
    response = requests.get(
        f'https://{GITEA_DOMAIN}/api/v1/repos/{GITEA_REPO}/labels',
        headers=GITEA_HEADERS
    )

    for label in json.loads(response.content):
        result[label['name']] = label['id']

    return result


def get_comments(issue_id: int) -> dict:
    """Get all comments of an issue in Redmine

    Args:
        issue_id (int): the ID of the issue in Redmine

    Returns:
        [dict]: The comments of the issue
    """
    response = requests.get(f'https://{REDMINE_DOMAIN}/' +
        f'issues/{issue_id}.json?include=journals', headers=REDMINE_HEADERS)

    return json.loads(response.content)['issue']['journals']


def add_labels(issue_id: int, labels: list, user: str) -> List:
    """Add labels to an issue

    Args:
        issue_id (int): ID of the issue in Gitea
        labels (list): List of label ids
        user (str): Who is adding the label?

    Returns:
        [List]: List of all current labels of the issue
    """
    data = {
        'labels': labels
    }

    response = requests.post(
        f'https://{GITEA_DOMAIN}/api/v1/repos/{GITEA_REPO}/issues/{issue_id}/labels?sudo={user}',
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    return [x['id'] for x in json.loads(response.content)]


def add_comment(issue_id: int, body: str, user: str) -> None:
    """Add comment to an issue in Gitea

    Args:
        issue_id (int): ID of the issue in Gitea
        body (str): The comment's description
        user (str): Who is adding the comment?
    """
    data = {
        'body': body
    }

    response = requests.post(
        f'https://{GITEA_DOMAIN}/api/v1/repos/{GITEA_REPO}/issues/{issue_id}/comments?sudo={user}',
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    if not response.ok:
        print(response.content)
        raise SystemExit()


def get_username(users: dict, id: int) -> str:
    if id in users:
        return users[id]['username']

    return DEFAULT_USERNAME


def create_issue(issue: dict, labels: dict, projects: dict, users: dict) -> None:
    """Creates an issue in Gitea given the json data of Redmine's API.

    Args:
        issue (dict): The data of the issue from Redmine.
        labels (dict): The labels of the repo in Gitea.
    """
    id = issue['id']
    subject = issue['subject']
    description = issue['description'].replace('\r\n', '\n')
    status = issue['status']['name']
    custom_fields = [f'| {x["name"]} | {x["value"]} |' for x in issue['custom_fields'] if x['value'] != '']
    issue_type = issue['tracker']['name']
    priority = issue['priority']['name']
    is_private = issue['is_private']
    done_ratio = issue['done_ratio']
    category = '-'

    print(id, subject)

    if 'category' in issue:
        category = issue['category']

    assigned_to = '-'
    if 'assigned_to' in issue:
        assigned_to = issue['assigned_to']['name']
        assigned_to_username = get_username(users, issue['assigned_to']['id'])

    author = issue['author']['name']
    author_username = get_username(users, issue['author']['id'])

    if is_private:
        return

    body = f"""
{description}

***
*Imported from Redmine*
| Property      | Value             |
| ---           | ---               |
| ID            | #{id}             |
| Priority      | {priority}        |
| Status        | {status}          |
| Issue type    | {issue_type}      |
| Author        | {author}          |
| Assigned to   | {assigned_to}     |
| Category      | {category}        |
| Progress      | {done_ratio}%     |
"""
    if len(custom_fields) > 0:
        body += '\n'.join(custom_fields)

    data = {
        "title": subject,
        "body": body,
        "closed": status in ['Resolved', 'Closed', 'Rejected'],
    }

    if assigned_to != '-':
        data['assignee'] = assigned_to_username

    issue_type_map = {
        'Bug': 'bug',
        'Feature': 'enhancement',
        'Support': 'support',
    }
    data['labels'] = [labels[issue_type_map[issue_type]]]

    if status == 'Rejected':
        data['labels'].append(labels['wontfix'])

    response = requests.post(
        f'https://{GITEA_DOMAIN}/{GITEA_ENDPOINT}?sudo={author_username}',
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    if response.status_code == 422:
        print(f'\tCould not assign assignee: {assigned_to_username}, retrying without assignee...')
        del data['assignee']
    response = requests.post(
        f'https://{GITEA_DOMAIN}/{GITEA_ENDPOINT}?sudo={author_username}',
            headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    if not response.ok:
        print(f'Error while creating issue ({response.status_code}):', response.content)
        raise SystemExit()

    response_json = json.loads(response.content)
    gitea_issue_id = response_json['number']
    comments = get_comments(id)

    if 'labels' in response_json:
        gitea_labels = [x['id'] for x in response_json['labels']]
        while gitea_labels != data['labels']:
            print(f'\tCreated labels ({gitea_labels}) do not match expected labels ({data["labels"]}) for gitea issue {gitea_issue_id}, retrying...')
            time.sleep(0.5)
            gitea_labels = add_labels(gitea_issue_id, data['labels'], author_username)

    map_status = {
        1: 'New',
        2: 'In Progress',
        3: 'Resolved',
        4: 'Feedback',
        5: 'Closed',
        6: 'Rejected',
        8: 'Review requested',
        9: 'Review provided',
        10: 'Ready for deploy',
    }

    issue_type_map = {
        1: 'Bug',
        2: 'Feature',
        3: 'Support',
    }

    for comment in comments:
        notes = comment['notes']
        created_on_obj = datetime.datetime.fromisoformat(comment['created_on'].replace('Z', '+00:00'))
        created_on = created_on_obj.astimezone(pytz.timezone('Europe/Amsterdam')).strftime('%d %B %Y at %H:%M')
        details = comment['details']
        user = get_username(users, comment['user']['id'])
        detail_text = []

        for detail in details:
            property = detail['property']
            property_name = detail['name']
            old_value = detail['old_value']
            new_value = detail['new_value']
            unit = ''
            prefix_old = ''
            prefix_new = ''

            if property_name == 'done_ratio':
                unit = '%'
            elif property_name in ['blocked', 'precedes', 'relates']:
                if old_value is not None:
                    prefix_old = '#'
                if new_value is not None:
                    prefix_new = '#'

            if old_value == '':
                old_value = 'None'

            if property_name == 'status_id':
                old_value = map_status[int(old_value)]
                new_value = map_status[int(new_value)]

            if property_name == 'tracker_id':
                old_value = issue_type_map[int(old_value)]
                new_value = issue_type_map[int(new_value)]

            if property_name == 'project_id':
                old_value = projects[int(old_value)]
                new_value = projects[int(new_value)]

            if property_name == 'assigned_to_id':
                if old_value != None:
                    old_value = users[int(old_value)]['name']
                if new_value != None:
                    new_value = users[int(new_value)]['name']

            if not property_name.isnumeric():
                if property_name in ['subject', 'description']:
                    old_value = old_value.replace('\n', '\n> ')
                    new_value = new_value.replace('\n', '\n> ')
                    detail_text.append(f'`{property_name}` changed from:\n> {prefix_old}{old_value}{unit}\n\nto:\n\n> {prefix_new}{new_value}{unit}\n')
                else:
                    detail_text.append(f'*`{property_name}` changed from {prefix_old}{old_value}{unit} to {prefix_new}{new_value}{unit}*')

        body = notes + ('\n***\n' if len(notes) > 0 and len(detail_text) > 0 else '') + '\n'.join(detail_text) + f'\n\n*Date: {created_on}*'
        add_comment(gitea_issue_id, body, user)


process_issues()
