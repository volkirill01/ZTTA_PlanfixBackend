# class Task:
#     def __init__(self, task_id, template_id):
#         self.task_id = task_id
#         self.template_id = template_id
#         self.children = []
#
#     def add_child(self, child_task):
#         self.children.append(child_task)
#
#     def print_children(self, level = 0):
#         print(f"{'  ' * level}Task(task_id={self.task_id}, template_id={self.template_id}) child_count={len(self.children)}")
#         level += 1
#         for child in self.children:
#             child.print_children(level)
#
#     # def __repr__(self, level=0):
#     #     indent = "  " * level
#     #     rep = f"{indent}Task(task_id={self.task_id}, template_id={self.template_id})\n"
#     #     for child in self.children:
#     #         rep += child.__repr__(level + 1)
#     #     return rep

class Task:
    def __init__(self, task_id: int, template_id: int):
        self.task_id = task_id
        self.template_id = template_id
        self.cutting_needed = None  # default None for non-leaf
        self.work_belongs_to_assembly = None  # default None for non-leaf
        self.work_belongs_to_order = None  # default None for non-leaf

        self.children = []

        self.dvg_file_id = 0

    def get_id(self): return self.task_id

    def add_child(self, child):
        self.children.append(child)
        return self.children[-1]

    def get_last_child(self): return self.children[-1]

    def print_children(self, level: int = 0):
        print(f"{'  ' * level}{self.task_id}{' cutting' if self.cutting_needed else ''}{' assembly_work' if self.work_belongs_to_assembly else ''}{' order_work' if self.work_belongs_to_order else ''}") #planfix_get(f"task/{self._id}?fields=name&sourceId=0").json()["task"]["name"]
        level += 1
        for child in self.children:
            child.print_children(level)

    def __str__(self): return str(self.task_id)


def recreate_task_tree_from_list(order_id, task_ids, template_ids, subtask_counts, cutting_needed, work_belongs_to_assembly, work_belongs_to_order):
    TEMPLATE_WORK = 8732007
    tasks = [Task(tid, tmpl_id) for tid, tmpl_id in zip(task_ids, template_ids)]
    root = Task(order_id, 0)

    index = 0
    sub_index = 0
    leaf_counter = 0

    def parse_subtree():
        nonlocal index, sub_index, leaf_counter
        start_index = index  # <- define here!

        task = tasks[index]
        index += 1

        if task.template_id == TEMPLATE_WORK:
            # Leaf node, no descendants
            task.cutting_needed = cutting_needed[leaf_counter]
            task.work_belongs_to_assembly = work_belongs_to_assembly[leaf_counter]
            task.work_belongs_to_order = work_belongs_to_order[leaf_counter]
            leaf_counter += 1
            return task

        descendant_count = subtask_counts[sub_index]
        sub_index += 1

        consumed = 0
        while consumed < descendant_count:
            child = parse_subtree()
            task.add_child(child)
            consumed = index - start_index - 1  # number of descendants consumed so far

        return task

    while index < len(tasks):
        root.add_child(parse_subtree())

    return root

order_id = 17156
# task_ids =       [17157, 17159, 17160, 17161, 17169, 17170, 17162, 17164, 17165, 17171, 17158, 17166, 17167, 17172]
# template_ids =   [8732191, 8732191, 8732005, 8732007, 8732007, 8732007, 8732191, 8732005, 8732007, 8732007, 8732191, 8732005, 8732007, 8732007]
# subtask_counts = [9, 4, 3, 3, 2, 3, 2]
# work_belongs_to_assembly = [False, False, False, False, False, False, False]
# work_belongs_to_order = [False, False, False, False, False, False, False]

# task_ids = [17157, 17159, 17160, 17161, 17169, 17170, 17175, 17176, 17162, 17164, 17165, 17171, 17158, 17166, 17167, 17172, 17177]
# template_ids = [8732191, 8732191, 8732005, 8732007, 8732007, 8732007, 8732007, 8732007, 8732191, 8732005, 8732007, 8732007, 8732191, 8732005, 8732007, 8732007, 8732007]
# subtask_counts = [11, 6, 3, 3, 2, 3, 2]
# cutting_needed = [False, True, False, False, False, False, False, False, False, False]
# work_belongs_to_assembly = [False, False, False, True, True, False, False, False, False, False]
# work_belongs_to_order = [False, False, False, False, False, False, False, False, False, True]
#
# tree = recreate_task_tree_from_list(order_id, task_ids, template_ids, subtask_counts, cutting_needed, work_belongs_to_assembly, work_belongs_to_order)
# tree.print_children()





filename_format = "{detail_id}_{material}_{thickness}.extension"


# Развертка - балка б шаблон лево_СТ3_1_1шт итфыв.DWG
def parse_filename(filename: str):
    components = filename.split("_")

    if len(components) < 3:
        # if len(components) < 6:
        print(f"Filename \"{filename}\" incorrectly formatted. Format is \"{filename_format}\"")
        return { "error" }

    # try:
    #     order_number = int(components[0])
    # except Exception as e:
    #     print_error(f"{components[0]} Incorrect format for OrderNumber. Error is: {e}")
    #     return { "error": f"(Номер заказа) Неверный формат: {components[0]}" }

    # try:
    #     assembly_id = int(components[1])
    # except Exception as e:
    #     print_error(f"{components[1]} Incorrect format for AssemblyID. Error is: {e}")
    #     return { "error": f"(Номер сборки) Неверный формат: {components[1]}" }

    # try:
    #     detail_id = int(components[2])
    # except Exception as e:
    #     print_error(f"{components[2]} Incorrect format for DetailID. Error is: {e}")
    #     return { "error": f"(Номер детали) Неверный формат: {components[2]}" }
    detail_id = components[0]

    # material = components[3]
    material = components[1]
    # if material not in material_table:
    #     print_error(f"{material} Unknown material")
    #     return { "error": f"(Материал) Неизвестный Материал: {material}" }

    # try:
    #     thickness = int(components[4])
    # except Exception as e:
    #     print_error(f"{components[4]} Incorrect format for Thickness. Error is: {e}")
    #     return { "error": f"(Толщина) Неверный формат: {components[4]}" }
    try:
        thickness = components[2]
        if thickness.startswith("Т"):
            thickness = thickness[1:]

        thickness = int(thickness)
    except Exception as e:
        print(f"{components[2]} Incorrect format for Thickness. Error is: {e}")
        return {"error": f"(Толщина) Неверный формат: {components[2]}"}

    # try:
    #     quantity = int(components[5])
    # except Exception as e:
    #     print_error(f"{components[5]} Incorrect format for Quantity. Error is: {e}")
    #     return { "error": f"(Количество) Неверный формат: {components[5]}" }

    return {
        # "order_number": order_number,
        # "assembly_id": assembly_id,
        "detail_id": detail_id,
        "material": material,
        "thickness": thickness  # ,
        # "quantity": quantity
    }










name = "Развертка - балка б шаблон лево_СТ3_Т1_1шт итфыв.DWG"
print(parse_filename(name))

























# Expected tree view
# Task(task_id=0, template_id=0)
#   Task(task_id=17157, template_id=8732191)
#     Task(task_id=17159, template_id=8732191)
#       Task(task_id=17160, template_id=8732005)
#         Task(task_id=17161, template_id=8732007)
#     Task(task_id=17162, template_id=8732191)
#       Task(task_id=17164, template_id=8732005)
#         Task(task_id=17165, template_id=8732007)
#   Task(task_id=17158, template_id=8732191)
#     Task(task_id=17166, template_id=8732005)
#       Task(task_id=17167, template_id=8732007)

from data import *
import requests
import os

# def planfix_get(_url) -> requests.Response:
#     full_url = f"{BASE_URL}{_url}"
#
#     headers = {
#       'Accept': 'application/json',
#       "Authorization": f"Bearer {BEARER_TOKEN}"
#     }
#     return requests.request("GET", full_url, headers=headers, data={})
#
#
# def planfix_post(_url, _payload) -> requests.Response:
#     full_url = f"{BASE_URL}{_url}"
#
#     headers = {
#       "Authorization": f"Bearer {BEARER_TOKEN}"
#     }
#     return requests.post(full_url, headers=headers, json=_payload)


# filepath = "5966310.dwg"
# pdf_filepath = os.path.join("resources/tmp", filepath.split("\\")[-1].replace(".dwg", ".pdf")).replace("/", "\\")
# print(pdf_filepath)
# files = [
#     ('file', ("5966310.pdf", open(pdf_filepath, 'rb'), 'application/pdf'))
# ]
# headers = {
#     'Accept': 'application/json',
#     "Authorization": f"Bearer {BEARER_TOKEN}"
# }
# response = requests.request("POST", f"{BASE_URL}file/", headers=headers, files=files)
# print(response.json()["id"])


# Example code for Planfix team
# filepath = "5966310.pdf"
# files = [
#     ('file', (filepath, open(filepath, 'rb'), 'application/pdf'))
# ]
# headers = {
#     'Content-Type': 'multipart/form-data',
#     'Accept': 'application/json',
#     "Authorization": f"Bearer {BEARER_TOKEN}"
# }
# response = requests.request("POST", f"{BASE_URL}file/", headers=headers, data={}, files=files)
# print(response.json())



# files = planfix_get("task/12650?fields=105854").json()["task"]["customFieldData"][0]["value"]
# for file in files:
#     print(planfix_get(f"file/{file}").json())

# body = {
#     'name': 'example2.pdf',
#     'description': 'Описание!!!',
#     'processId': 77646,
#     'assigner': {'id': 79},
#     'template': {'id': 12381},  # 12382
#     'parent': {'id': 12662},
#     'auditors': {'users': [{'id': 15}]},
#     'assignees': {'users': [{'id': 15}]},
#     'participants': {'users': [{'id': 15}]},
#     'customFieldData': [
#         {
#             'field': {
#                  'id': 105598
#              },
#             'value': "Лазер Ermaksan"
#         },
#         {
#             'field': {
#                  'id': 105854
#              },
#             'value': 5966142
#         }
#     ]
# }
#
# print(planfix_post("/task", body).json())

# body = {
#   "name": "Задача из Python!!!",
#   "description": "Описание!!!",
#   "processId": 77646,  # Канбан: Тест1
#   "assigner": {"id": 79},  # TODO: Don't work
#   "template": {"id": 12381},  # Тест1
#   "auditors": {  # TODO: Don't work
#     "users": [
#       {"id": 15}
#     ]
#   },
#   "assignees": {  # TODO: Don't work
#     "users": [
#       {"id": 15}
#     ]
#   },
#   "participants": {  # TODO: Don't work
#     "users": [
#       {"id": 15}
#     ]
#   }
# }
#
# HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}
# print(requests.post(f"{BASE_URL}task/", headers=HEADERS, json=body).json())

# print(response.status_code)
# print(response.json())

# user_name = "Илья Никуленко"  # input("Enter user name: ")
#
# # Get all tasks from user ID
# body = {
#   "offset": 0,
#   "pageSize": 100,
#   "onlyActive": False,
#   "prefixedId": False,
#   "fields": "name,lastname",
#   "sourceId": "0",
#   "filters": []
# }
# response = requests.post(f"{BASE_URL}user/list", headers=HEADERS, json=body)
#
# # print(response.status_code)
# # print(response.json())
#
# found_id = 0
# for user in response.json()["users"]:
#     if user["name"] == user_name.split(" ")[0] and user["lastname"] == user_name.split(" ")[1]:
#         found_id = user["id"]
#
# # Get all tasks from user ID
# body = {
#   "offset": 0,
#   "pageSize": 100,
#   "fields": "name",
#   "filters": [
#     {
#         "type": 2,
#         "operator": "equal",
#         "value": f"user:{found_id}"
#     }
#   ]
# }
# response = requests.post(f"{BASE_URL}task/list", headers=HEADERS, json=body)
#
# print(response.status_code)
# print(response.json())
