import requests
import os
import json
import time
import datetime
import pytz
import re
from dotenv import load_dotenv
from typing import List, Dict

load_dotenv()

REDMINE_DOMAIN = os.getenv('REDMINE_DOMAIN')
REDMINE_API_TOKEN = os.getenv('REDMINE_API_TOKEN')
REDMINE_HEADERS = {
    'accept': 'application/json',
    'X-Redmine-API-Key': REDMINE_API_TOKEN,
    'Content-Type': 'application/json',
}

GITEA_DOMAIN = os.getenv('GITEA_DOMAIN')
GITEA_API_TOKEN = os.getenv('GITEA_API_TOKEN')
GITEA_HEADERS = {
    'accept': 'application/json',
    'Authorization': f'token {GITEA_API_TOKEN}',
    'Content-Type': 'application/json',
}

DEFAULT_USERNAME = os.getenv('DEFAULT_USERNAME')
ORGANIZATION = os.getenv('ORGANIZATION')

labels: Dict = {}
comments_to_update = []
map_redmine_to_gitea = {}
relation_types = [
    'blocks',
    'blocked',
    'precedes',
    'follows',
    'relates',
    'duplicates',
    'duplicated',
    'copied_to',
    'copied_from',
]


def get_gitea_repo(redmine_project_name: str) -> str:
    project_name = redmine_project_name.strip().lower()

    if project_name == 'nuno':
        project_name = 'nuno-api'
    elif project_name == 'cotton':
        project_name = 'tv'

    return f'{ORGANIZATION}/{project_name}'


def process_issues() -> None:
    issues = get_issues()
    projects = get_projects()
    users = get_users()

    try:
        for issue in issues:
            create_issue(issue, projects, users)
    finally:
        with open('map_redmine_to_gitea.json', 'w') as f:
            json.dump(map_redmine_to_gitea, f, sort_keys=True, indent=4)

    update_comments()


def update_comments() -> None:
    for comment in comments_to_update:
        content = comment['content']

        for match in comment['matches']:
            issue_id = int(match[1:])

            if issue_id in map_redmine_to_gitea:
                gitea_id = map_redmine_to_gitea[issue_id]
                content = content.replace(match, f'#{gitea_id} (redmine id: {issue_id})')
            else:
                print(f'Error: Could not find gitea issue id for redmine issue #{issue_id}.')

        edit_comment_body(comment['gitea_repo'], comment['issue_id'], comment['comment_id'], content)


def get_users() -> dict:
    """Returns all users as registered in Redmine.

    Returns:
        dict: Dict of (username, name) pairs for each user id
    """
    response = requests.get(f'{REDMINE_DOMAIN}/users.json', headers=REDMINE_HEADERS)
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
    response = requests.get(f'{REDMINE_DOMAIN}/projects.json', headers=REDMINE_HEADERS)
    result = {}

    for project in json.loads(response.content)['projects']:
        result[project['id']] = project['name']

    return result


def get_issues() -> List:
    """Get issues from the Redmine instance.

    Returns:
        dict: Issues with data in key-value pairs.
    """
    i = 0
    limit = 100
    result = []
    filename = 'issues.json'

    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)

    print('Loading issues...')
    while True:
        response = requests.get(f'{REDMINE_DOMAIN}/' +
            f'issues.json?status_id=*&limit={limit}&offset={i}', headers=REDMINE_HEADERS)
        json_response = response.json()['issues']

        for issue in json_response:
            result.append(issue)

        if len(json_response) < limit:
            break

        i += len(json_response)

    # Reverse order, oldest first.
    result = result[::-1]

    with open(filename, 'w') as f:
        json.dump(result, f, sort_keys=True, indent=4)

    return result


def get_labels(gitea_repo: str) -> dict:
    """Get the labels used for the repo in Gitea.

    Returns:
        dict: Pairs of (name, id) of all labels.
    """
    if gitea_repo in labels:
        return labels[gitea_repo]

    result = {}
    response = requests.get(
        f'{GITEA_DOMAIN}/api/v1/repos/{gitea_repo}/labels',
        headers=GITEA_HEADERS
    )

    for label in json.loads(response.content):
        result[label['name']] = label['id']

    labels[gitea_repo] = result
    return result


def get_comments(issue_id: int) -> dict:
    """Get all comments of an issue in Redmine

    Args:
        issue_id (int): the ID of the issue in Redmine

    Returns:
        [dict]: The comments of the issue
    """
    response = requests.get(
        f'{REDMINE_DOMAIN}/issues/{issue_id}.json?include=journals',
        headers=REDMINE_HEADERS
    )

    return json.loads(response.content)['issue']['journals']


def add_labels(gitea_repo: str, issue_id: int, labels: list, user: str) -> List:
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
        f'{GITEA_DOMAIN}/api/v1/repos/{gitea_repo}/issues/{issue_id}/labels?sudo={user}',
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    return [x['id'] for x in json.loads(response.content)]


def check_for_references(content: str, gitea_repo: str, issue_id: int, comment_id: str) -> None:
    matches = re.findall('(#[0-9]+)', content)
    if matches is not None and len(matches) > 0:
        comments_to_update.append({
            'gitea_repo': gitea_repo,
            'issue_id': issue_id,
            'comment_id': comment_id,
            'content': content,
            'matches': matches,
        })

        print(f'\tFound {len(matches)} issue reference(s) in repo {gitea_repo} for issue {issue_id} with comment id {comment_id}.')

def edit_comment_body(gitea_repo: str, issue_id: int, comment_id: int, body: str):
    data = {
        'body': body
    }
    if comment_id == 'body':
        url = f'{GITEA_DOMAIN}/api/v1/repos/{gitea_repo}/issues/{issue_id}'
    else:
        url = f'{GITEA_DOMAIN}/api/v1/repos/{gitea_repo}/issues/comments/{comment_id}'

    response = requests.patch(
        url,
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )



def add_comment(gitea_repo: str, issue_id: int, body: str, user: str) -> None:
    """Add comment to an issue in Gitea

    Args:
        issue_id (int): ID of the issue in Gitea
        body (str): The comment's description
        user (str): Who is adding the comment?
    """
    data = {
        'body': body
    }
    url = f'{GITEA_DOMAIN}/api/v1/repos/{gitea_repo}/issues/{issue_id}/comments?sudo={user}'

    response = requests.post(
        url,
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    if not response.ok:
        print(response.content)
        raise SystemExit()

    check_for_references(body, gitea_repo, issue_id, response.json()['id'])


def get_username(users: dict, id: int) -> str:
    if id in users:
        return users[id]['username']

    return DEFAULT_USERNAME if DEFAULT_USERNAME is not None else ''


def create_issue(issue: dict, projects: dict, users: dict) -> None:
    """Creates an issue in Gitea given the json data of Redmine's API.

    Args:
        issue (dict): The data of the issue from Redmine.
    """
    id = issue['id']
    subject = issue['subject']
    project = projects[int(issue['project']['id'])]
    description = issue['description'].replace('\r\n', '\n')
    status = issue['status']['name']
    custom_fields = [f'| {x["name"]} | {x["value"]} |' for x in issue['custom_fields'] if x['value'] is not None and x['value'] != '']
    issue_type = issue['tracker']['name']
    priority = issue['priority']['name']
    is_private = issue['is_private']
    done_ratio = issue['done_ratio']
    created_on_obj = datetime.datetime.fromisoformat(issue['created_on'].replace('Z', '+00:00'))
    created_on = created_on_obj.astimezone(pytz.timezone('Europe/Amsterdam')).strftime('%d %B %Y at %H:%M')
    category = '-'

    gitea_repo = get_gitea_repo(project)
    labels = get_labels(gitea_repo)

    print(id, subject)

    if 'category' in issue:
        category = issue['category']['name']

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
| Original ID   | {id}              |
| Created On    | {created_on}      |
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
    data['labels'].append(labels['migrated'])

    if status == 'Rejected':
        data['labels'].append(labels['wontfix'])

    data['labels'].sort()
    endpoint = f'{GITEA_DOMAIN}/api/v1/repos/{gitea_repo}/issues'

    response = requests.post(
        f'{endpoint}?sudo={author_username}',
        headers=GITEA_HEADERS,
        data=json.dumps(data)
    )

    if response.status_code == 422:
        print(f'\tCould not assign assignee: {assigned_to_username}, retrying without assignee...')
        del data['assignee']

        response = requests.post(
            f'{endpoint}?sudo={author_username}',
            headers=GITEA_HEADERS,
            data=json.dumps(data)
        )

    if not response.ok:
        print(f'Error while creating issue ({response.status_code}):', response.content)
        print(data)
        raise SystemExit()


    response_json = json.loads(response.content)
    gitea_issue_id = response_json['number']
    comments = get_comments(id)
    map_redmine_to_gitea[int(id)] = gitea_issue_id

    check_for_references(description, gitea_repo, gitea_issue_id, 'body')

    if 'labels' in response_json:
        gitea_labels = [x['id'] for x in response_json['labels']]
        gitea_labels.sort()

        while gitea_labels != data['labels']:
            print(f'\tCreated labels ({gitea_labels}) do not match expected labels ({data["labels"]}) for gitea issue {gitea_issue_id}, retrying...')
            time.sleep(0.5)
            gitea_labels = add_labels(gitea_repo, gitea_issue_id, data['labels'], author_username)
            gitea_labels.sort()

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
            elif property_name in relation_types:
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
                if old_value != None and int(old_value) in users:
                    old_value = users[int(old_value)]['name']
                if new_value != None and int(new_value) in users:
                    new_value = users[int(new_value)]['name']

            if not property_name.isnumeric():
                if property_name in ['subject', 'description']:
                    old_value = old_value.replace('\n', '\n> ')
                    new_value = new_value.replace('\n', '\n> ')
                    detail_text.append(f'`{property_name}` changed from:\n> {prefix_old}{old_value}{unit}\n\nto:\n\n> {prefix_new}{new_value}{unit}\n')
                else:
                    detail_text.append(f'*`{property_name}` changed from {prefix_old}{old_value}{unit} to {prefix_new}{new_value}{unit}*')

        body = ''
        if notes is not None and len(notes) > 0:
            body = notes + ('\n***\n' if len(detail_text) > 0 else '')

        body += '\n'.join(detail_text) + f'\n\n*Date: {created_on}*'

        if user == DEFAULT_USERNAME:
            body += f'\n*User: {comment["user"]["name"]}*'

        add_comment(gitea_repo, gitea_issue_id, body, user)


if __name__ == '__main__':
    process_issues()
