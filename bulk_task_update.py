from base import *
from planfix_api import *

update_type_list = [
    "Добавить Аудитора(\"Давран во всех заказах\", \"Никуленко в заказах ОМА\", \"Олейников в заказах Конструкторов\")",
    "Добавить Учасника(Следят за задачей но ничего не могут сделать \"Операторы на станках\")",
    "Добавить Исполнителя(Играют какую то роль в выполнении задачи \"Гена для подписей сварки\", \"На этапе вывода УП все из вывода УП\")"]

def get_users():
    user_request_body = {
        "offset": 0,
        "pageSize": 100,
        "onlyActive": False,
        "fields": "id,name,lastname",
        "sourceId": 0
    }
    return planfix_post("user/list", user_request_body).json()["users"]

def update_tasks(request_body, update_type_index, user_id):
    #match update_type_index:
    #    case 0:

    tasks = planfix_post("task/list", request_body).json()["tasks"]

    print(user_id)
    print(update_type_list[update_type_index])


    # while len(tasks) != 0:
    #     for task in tasks:
    #
    #
    #         tasks.remove(task)

if __name__ == "__main__":
    # processes = planfix_get("process/task?fields=id,name").json()["processes"]
    # for i in range(len(processes)):
    #     process = processes[i]
    #     print(f"[{i}] {'{ id: ' + str(process['id']) + ', name: ' + process['name'] + ' }'}")
    #
    # selected_process_index = int(input("Выберите процесс: "))
    #
    # print(processes[selected_process_index]["id"])

    templates = planfix_get("task/templates?offset=0&pageSize=100&sourceId=0&fields=id,name").json()["templates"]
    for i in range(len(templates)):
        template = templates[i]
        print(f"[{i}] {template['name']}")

    selected_template_index = int(input("Выберите шаблон(Индекс из списка выше): "))

    task_request_body = {
        "offset": 0,
        "pageSize": 10,
        "filters": [
            {
                "type": 51,
                "operator": "equal",
                "value": int(templates[selected_template_index]["id"])
            }
        ],
        "fields": "id,name,participants,auditors,assignees",
        "sourceId": 0
    }
    print("Доступные задачи(Первые 10):", planfix_post("task/list", task_request_body).json()["tasks"])

    for i in range(len(update_type_list)):
        print(f"[{i}] {update_type_list[i]}")
    selected_update_type_index = int(input("Что сделать с задачами(Индекс из списка выше): "))

    users = get_users()
    for i in range(len(users)):
        if len(str(users[i]['lastname'])) != 0:
            print(f"[{i}] {users[i]['lastname'][0]}. {users[i]['name']}")
        else:
            print(f"[{i}] {users[i]['name']}")

    match selected_update_type_index:
        case 0:
            selected_auditor_index = int(input("Выберите Аудитора(Индекс из списка выше): "))
            selected_user_id = users[selected_auditor_index]["id"]
        case 1:
            selected_participant_index = int(input("Выберите Учасника(Индекс из списка выше): "))
            selected_user_id = users[selected_participant_index]["id"]
        case 2:
            selected_assigner_index = int(input("Выберите Исполнителя(Индекс из списка выше): "))
            selected_user_id = users[selected_assigner_index]["id"]
        case _:
            selected_user_id = -1

    task_request_body["pageSize"] = 100
    update_tasks(task_request_body, selected_update_type_index, selected_user_id)
