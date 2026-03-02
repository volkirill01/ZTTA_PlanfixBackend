import os
import re
from time import sleep

import aiohttp
from aiohttp import web
import aiohttp_cors
from trafaret import catch

from igs_generator.igs_generator import IGSGenerator
from planfix_api import *
from base import *
import requests
# from converter import convert_to_pdf, clean_dwg_files, clean_tmp_files
from dxf_generator.dxf_generator import DXFGenerator
from structs import *

import logging

TEMPLATE_DETAIL = 8732005
TEMPLATE_WORK = 8732007

HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 10210))

routes = web.RouteTableDef()
app = aiohttp.web.Application()
tmp_dir = os.path.abspath("resources/tmp")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def clean_tmp_files():
    for filename in os.listdir(tmp_dir):
        file_path = os.path.join(tmp_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
        except Exception as e:
            print_error('Failed to delete %s. Reason: %s' % (file_path, e))


def download_file(_filepath, _file_data):
    with open(_filepath, 'wb') as f:
        f.write(_file_data)


def get_list_field_values(task_id: int, field_id: int):
    values = planfix_get(f"customfield/task/{task_id}?fields=id,enumValues").json()["customfields"]
    for value in values:
        if value["id"] == field_id:
            return value["enumValues"]

    return []


def get_user_group_id_from_name(group_name: str):
    if len(group_name) == 0:
        return -1

    values = planfix_get("user/groups?fields=id,name").json()["groups"]
    for value in values:
        if value["name"] == group_name:
            return int(value["id"])

    return []


def filename_format_to_ru(filename_format: str):
    filename_format = filename_format.replace("order_number", "Номер заказа")
    filename_format = filename_format.replace("assembly_id", "Номер сборки")
    filename_format = filename_format.replace("part_id", "Номер детали")
    filename_format = filename_format.replace("material", "Материал")
    filename_format = filename_format.replace("thickness", "Толщина")
    filename_format = filename_format.replace("quantity", "Количество")
    filename_format = filename_format.replace(".extension", "")

    return filename_format


# material_table = {
#     "МС",
#     "СС",
#     "АС",
#     "Нерж",
#     "СТ3"
# }

# filename_format = "{order_number}_{assembly_id}_{detail_id}_{material}_{thickness}_{quantity}.extension"
filename_format = "{detail_id}_{material}_{thickness}.extension"


# Развертка - балка б шаблон лево_СТ3_Т1_1шт итфыв.DWG
def parse_filename(filename: str):
    components = filename.split("_")

    if len(components) < 3:
        # if len(components) < 6:
        print_error(f"Filename \"{filename}\" incorrectly formatted. Format is \"{filename_format}\"")
        return {
            "error": f"Неверный формат названия файла: \"{filename}\". Корректный формат: \"{filename_format_to_ru(filename_format)}\""}

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
        print_error(f"{components[2]} Incorrect format for Thickness. Error is: {e}")
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


class Task:
    def __init__(self, task_id: int, template_id: int):
        self.task_id = task_id
        self.template_id = template_id
        self.cutting_needed = None
        self.work_belongs_to_assembly = None
        self.work_belongs_to_order = None

        self.parent = None
        self.children = []

        self.dvg_file_ids = []

    def get_id(self):
        return self.task_id

    def is_detail_task(self):
        return self.template_id == TEMPLATE_DETAIL
    def is_work_task(self):
        return self.template_id == TEMPLATE_WORK

    def add_child(self, child):
        child.parent = self
        self.children.append(child)
        return self.children[-1]

    def get_last_child(self):
        return self.children[-1]

    def get_all_children(self):
        result = self.children

        for child in self.children:
            result += child.get_all_children()

        return result

    def print_children(self, level: int = 0):
        logging.info(
            f"{'  ' * level}{self.task_id}{' cutting' if self.cutting_needed else ''}{' assembly_work' if self.work_belongs_to_assembly else ''}{' order_work' if self.work_belongs_to_order else ''}")  # planfix_get(f"task/{self._id}?fields=name&sourceId=0").json()["task"]["name"]
        level += 1
        for child in self.children:
            child.print_children(level)

    def __str__(self):
        return str(self.task_id)


# TODO: This is not the best solution, we should just use parent task id's with children task id's instead of all of this template, children count nonsense
def recreate_task_tree_from_list(order_id, task_ids, template_ids, subtask_counts, cutting_needed, work_belongs_to_assembly, work_belongs_to_order):
    tasks = [Task(int(tid), int(tmpl_id)) for tid, tmpl_id in zip(task_ids, template_ids)]
    root = Task(order_id, 0)

    index = 0
    sub_index = 0
    leaf_counter = 0
    current_work_counter = 0

    def parse_subtree():
        nonlocal index, sub_index, leaf_counter, current_work_counter
        start_index = index  # <- define here!

        task = tasks[index]
        index += 1

        if task.template_id == TEMPLATE_WORK:
            # Leaf node, no descendants
            task.cutting_needed = cutting_needed[current_work_counter] == "Да"
            task.work_belongs_to_assembly = work_belongs_to_assembly[leaf_counter] == "Да"
            task.work_belongs_to_order = work_belongs_to_order[leaf_counter] == "Да"
            leaf_counter += 1
            current_work_counter += 1
            return task
        elif task.template_id == TEMPLATE_DETAIL:
            current_work_counter += 1

        descendant_count = int(subtask_counts[sub_index])
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


@routes.post("/copy_assembly_status_to_order")
async def copy_assembly_status_to_order(request: web.Request):
    try:
        body = await request.json()

        order_id = int(body["order_id"])
        order_status_id = int(body["order_status_id"])
        subtask_status_id = int(body["subtask_status_id"])

        logging.info("\ncopy_assembly_status_to_order")
        logging.info("order_id %d", order_id)
        logging.info("order_status_id %d", order_status_id)
        logging.info("subtask_status_id %d", subtask_status_id)

        if order_status_id == subtask_status_id:
            return web.HTTPOk()

        body = {
            "status": {"id": subtask_status_id}
        }
        planfix_post(f"task/{order_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/recalculate_unused_details")
async def recalculate_unused_details(request: web.Request):
    try:
        body = await request.json()

        work_task_id = int(body["work_task_id"])
        all_detail_ids = body["all_detail_ids"]
        used_detail_ids = body["used_detail_ids"][0].split(",") if len(body["used_detail_ids"]) > 0 else []

        logging.info("\nrecalculate_unused_details")
        logging.info("work_task_id %d", work_task_id)
        logging.info("all_detail_ids %s", all_detail_ids)
        logging.info("used_detail_ids %s", used_detail_ids)

        _set = set(used_detail_ids)
        result = [x for x in all_detail_ids if x not in _set]
        logging.info("result %s", result)

        body = {
            "customFieldData": [
                {
                    "field": {"id": 106026},  # Неиспользованные детали
                    "value": result
                }
            ]
        }
        planfix_post(f"task/{work_task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/add_workers")
async def add_workers(request: web.Request):
    try:
        body = await request.json()

        detail_task_id = int(body["detail_task_id"])
        detail_worker_names_init = body["detail_worker_names"]
        detail_worker_names = detail_worker_names_init if len(detail_worker_names_init) > 1 else detail_worker_names_init[0].split(",")
        detail_work_task_ids = body["detail_work_task_ids"]

        logging.info("\nadd_workers")
        logging.info("detail_task_id %d", detail_task_id)
        logging.info("detail_worker_names__start_value %s", detail_worker_names_init)
        logging.info("detail_worker_names %s", detail_worker_names)
        logging.info("detail_work_task_ids %s", detail_work_task_ids)

        detail_worker_names_tmp = detail_worker_names
        detail_worker_names = []
        for detail_worker_name in detail_worker_names_tmp:
            detail_worker_name = detail_worker_name.replace("[", "") if detail_worker_name[0] == "[" else detail_worker_name
            detail_worker_name = detail_worker_name.replace("]", "") if detail_worker_name[-1] == "]" else detail_worker_name
            detail_worker_name_ss = detail_worker_name.split(",")
            for tmp in detail_worker_name_ss:
                detail_worker_names.append(tmp)
        logging.info("detail_worker_names %s", detail_worker_names)

        detail_workers = []
        for worker_group_name in detail_worker_names:
            detail_workers.append({"id": get_user_group_id_from_name(worker_group_name)})

        logging.info("detail_workers %s", detail_workers)

        for task_id in detail_work_task_ids:
            task_id = int(task_id)

            old_assignees = planfix_get(f"task/{task_id}?fields=assignees&sourceId=0").json()["task"]["assignees"]
            old_group_list = old_assignees["groups"]
            old_user_list = []
            for user in old_assignees["users"]:
                old_user_list.append({"id": "user:" + str(user["id"]).replace("user:", "")})

            new_group_id_list = []
            for old_group in old_group_list:
                new_group_id_list.append({"id": old_group["id"]})
            for detail_worker in detail_workers:
                if detail_worker not in new_group_id_list:
                    new_group_id_list.append(detail_worker)

            planfix_post(f"task/{task_id}?silent=false", {"assignees": {"users": old_user_list, "groups": new_group_id_list}})

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/set_current_work_to_parent_and_movement_between_departments")
async def set_current_work_to_parent_and_movement_between_departments(request: web.Request):
    try:
        body = await request.json()

        if str(body["current_work_id"]) == '':
            return web.HTTPOk()

        work_task_ids = body["work_task_ids"]
        work_task_status_ids = body["work_task_status_ids"]
        parent_task_id = int(body["parent_task_id"])
        current_work_id = int(body["current_work_id"])
        previous_work_id = int(body["previous_work_id"])

        logging.info("\nset_current_work_to_parent_and_movement_between_departments")
        logging.info("work_task_ids %s", work_task_ids)
        logging.info("work_task_status_ids %s", work_task_status_ids)
        logging.info("parent_task_id %d", parent_task_id)
        logging.info("current_work_id %d", current_work_id)
        logging.info("previous_work_id %d", previous_work_id)

        work_directory_id = 14
        current_work_group_id = int(planfix_get(f"directory/{work_directory_id}/entry/{current_work_id}?fields=parentKey").json()["entry"]["parentKey"])
        previous_work_group_id = int(planfix_get(f"directory/{work_directory_id}/entry/{previous_work_id}?fields=parentKey").json()["entry"]["parentKey"])

        logging.info("current_work_group_id %d", current_work_group_id)
        logging.info("previous_work_group_id %d", previous_work_group_id)

        if current_work_group_id != previous_work_group_id:
            body = {
                "customFieldData": [
                    {
                        "field": {"id": 105881},  # Текущая Обработка
                        "value": {"id": current_work_id}
                    }
                ],
                "status": {"id": 217}  # Перемещение между подразделениями
            }
            planfix_post(f"task/{parent_task_id}?silent=false", body)

            for i, work_task_id_str in enumerate(work_task_ids):
                work_task_id = int(work_task_id_str)
                work_task_status_id = int(work_task_status_ids[i])

                if work_task_status_id == 2:  # В работе
                    body = {
                        "status": {"id": 217},  # Перемещение между подразделениями
                    }
                    planfix_post(f"task/{work_task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/reset_order_after_return_from_work")
async def reset_order_after_return_from_work(request: web.Request):
    try:
        body = await request.json()

        order_id = int(body["order_id"])
        sub_task_ids = body["sub_task_ids"]
        sub_task_template_ids = body["sub_task_template_ids"]
        work_belongs_to_assembly = body["work_belongs_to_assembly"]
        work_belongs_to_order = body["work_belongs_to_order"]
        subtask_counts = body["subtask_counts"].split(",")

        logging.info("\nreset_order_after_return_from_work")
        logging.info("sub_task_ids %s", sub_task_ids)
        logging.info("sub_task_template_ids %s", sub_task_template_ids)
        logging.info("work_belongs_to_assembly %s", work_belongs_to_assembly)
        logging.info("work_belongs_to_order %s", work_belongs_to_order)
        logging.info("subtask_counts %s", subtask_counts)

        _tmp = []
        for i in range(len(sub_task_ids)):
            _tmp.append("Нет")
        task_tree = recreate_task_tree_from_list(order_id, sub_task_ids, sub_task_template_ids, subtask_counts, _tmp, work_belongs_to_assembly, work_belongs_to_order)
        task_tree.print_children()

        all_children = task_tree.get_all_children()
        for child_task in all_children:
            if child_task.template_id == 8732007:  # Работа
                if child_task.work_belongs_to_assembly:
                    body = {
                        "status": {"id": 207},  # Конструкторский отдел
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": False
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
                elif child_task.work_belongs_to_order:
                    body = {
                        "status": {"id": 207},  # Конструкторский отдел
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": False
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
            elif child_task.template_id == 8732005:  # Деталь
                detail_work = planfix_get(f"task/{child_task.get_id()}?fields=105879&sourceId=0").json()["task"]["customFieldData"][0]["value"]  # 105879 - Типы обработки
                body = {
                    "customFieldData": [
                        {
                            "field": {"id": 105881},  # Текущая Обработка
                            "value": {"id": detail_work[0]["id"]}
                        }
                    ]
                }
                planfix_post(f"task/{child_task.get_id()}?silent=false", body)

        # Sleeping and sending requests in that particular order is necessary because of Planfix limitations
        sleep(1)
        is_first_work = True
        for child_task in all_children:
            if child_task.template_id == 8732007:  # Работа
                if child_task.work_belongs_to_assembly:
                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": True
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
                elif child_task.work_belongs_to_order:
                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": True
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
                else:
                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": 105967},  # Принять работу
                                "value": ""
                            }
                        ]
                    }
                    if not is_first_work:
                        body["status"] = {"id": 0}  # Черновик

                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)

                is_first_work = False
            else:
                is_first_work = True

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/reset_assembly_after_return_from_work")
async def reset_assembly_after_return_from_work(request: web.Request):
    try:
        body = await request.json()

        assembly_id = int(body["assembly_id"])
        sub_task_ids = body["sub_task_ids"]
        sub_task_template_ids = body["sub_task_template_ids"]
        work_belongs_to_assembly = body["work_belongs_to_assembly"]
        work_belongs_to_order = body["work_belongs_to_order"]
        subtask_counts = body["subtask_counts"].split(",")

        logging.info("\nreset_assembly_after_return_from_work")
        logging.info("assembly_id %d", assembly_id)
        logging.info("sub_task_ids %s", sub_task_ids)
        logging.info("sub_task_template_ids %s", sub_task_template_ids)
        logging.info("work_belongs_to_assembly %s", work_belongs_to_assembly)
        logging.info("work_belongs_to_order %s", work_belongs_to_order)
        logging.info("subtask_counts %s", subtask_counts)

        _tmp = []
        for i in range(len(sub_task_ids)):
            _tmp.append("Нет")
        task_tree = recreate_task_tree_from_list(assembly_id, sub_task_ids, sub_task_template_ids, subtask_counts, _tmp, work_belongs_to_assembly, work_belongs_to_order)
        task_tree.print_children()

        all_children = task_tree.get_all_children()
        for child_task in all_children:
            if child_task.template_id == 8732007:  # Работа
                if child_task.work_belongs_to_assembly:
                    body = {
                        "status": {"id": 207},  # Конструкторский отдел
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": False
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
                elif child_task.work_belongs_to_order:
                    body = {
                        "status": {"id": 207},  # Конструкторский отдел
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": False
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
            elif child_task.template_id == 8732005:  # Деталь
                detail_work = planfix_get(f"task/{child_task.get_id()}?fields=105879&sourceId=0").json()["task"]["customFieldData"][0]["value"]  # 105879 - Типы обработки
                body = {
                    "customFieldData": [
                        {
                            "field": {"id": 105881},  # Текущая Обработка
                            "value": {"id": detail_work[0]["id"]}
                        }
                    ]
                }
                planfix_post(f"task/{child_task.get_id()}?silent=false", body)

        # Sleeping and sending requests in that particular order is necessary because of Planfix limitations
        sleep(1)
        is_first_work = True
        for child_task in all_children:
            if child_task.template_id == 8732007:  # Работа
                if child_task.work_belongs_to_assembly:
                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": True
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
                elif child_task.work_belongs_to_order:
                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": 105947},  # Удалить задачу
                                "value": True
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)
                else:
                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": 105967},  # Принять работу
                                "value": ""
                            }
                        ]
                    }
                    if not is_first_work:
                        body["status"] = {"id": 0}  # Черновик

                    planfix_post(f"task/{child_task.get_id()}?silent=false", body)

                is_first_work = False
            else:
                is_first_work = True

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/accept_cutting_job")
async def accept_cutting_job(request: web.Request):
    try:
        body = await request.json()

        cutting_work_type = int(body["cutting_work_type"])
        detail_work_task_ids = body["detail_work_task_ids"][0].split(",")
        detail_work_task_work_types = body["detail_work_task_work_types"][0].split(",")

        logging.info("\naccept_cutting_job")
        logging.info("cutting_work_type %s", cutting_work_type)
        logging.info("detail_work_task_ids %s", detail_work_task_ids)
        logging.info("detail_work_task_work_types %s", detail_work_task_work_types)

        for i, work_task_id in enumerate(detail_work_task_ids):
            if cutting_work_type == int(detail_work_task_work_types[i]):
                body = {
                    "status": {"id": 2},  # В работе
                    "customFieldData": [
                        {
                            "field": {"id": 105967},  # Принять работу
                            "value": ""
                        }
                    ]
                }
                planfix_post(f"task/{int(work_task_id)}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/set_parent_status_if_child_status_not_equal")
async def set_parent_status_if_child_status_not_equal(request: web.Request):
    try:
        body = await request.json()

        parent_task_id = int(body["parent_task_id"])
        children_status_ids = body["children_status_ids"]
        desired_children_status_id = int(body["desired_children_status_id"])
        new_parent_status_id = int(body["new_parent_status_id"])

        logging.info("\nset_parent_status_if_child_status_not_equal")
        logging.info("parent_task_id %d", parent_task_id)
        logging.info("children_status_ids %s", children_status_ids)
        logging.info("desired_children_status_id %d", desired_children_status_id)

        if len(children_status_ids) != 0:
            all_desired = True
            for child_status_id in children_status_ids:
                if int(child_status_id) == desired_children_status_id:
                    all_desired = False

            if all_desired:
                body = {
                    "status": {"id": new_parent_status_id}
                }
                planfix_post(f"task/{parent_task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/copy_child_status_to_parent")
async def copy_child_status_to_parent(request: web.Request):
    try:
        body = await request.json()

        parent_task_id_str = str(body["parent_task_id"])
        if parent_task_id_str == '':
            return web.HTTPOk()

        parent_task_id = int(parent_task_id_str)
        children_status_ids = body["children_status_ids"]

        logging.info("\ncopy_child_status_to_parent")
        logging.info("parent_task_id %d", parent_task_id)
        logging.info("children_status_ids %s", children_status_ids)

        if len(children_status_ids) != 0:
            all_same = True
            previous_status_id = 0
            for child_status_id in children_status_ids:
                if previous_status_id != 0 and previous_status_id != int(child_status_id):
                    all_same = False

                previous_status_id = int(child_status_id)

            if all_same:
                body = {
                    "status": {"id": previous_status_id}
                }
                planfix_post(f"task/{parent_task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/copy_parent_status_to_children")
async def copy_parent_status_to_children(request: web.Request):
    try:
        body = await request.json()

        parent_task_id = int(body["parent_task_id"])
        parent_status_id = int(body["parent_status_id"])
        children_ids = body["children_ids"]
        children_status_ids = body["children_status_ids"]

        logging.info("\ncopy_parent_status_to_children")
        logging.info("parent_task_id %d", parent_task_id)
        logging.info("parent_status_id %d", parent_status_id)
        logging.info("children_ids %s", children_ids)
        logging.info("children_status_ids %s", children_status_ids)

        body = {
            "status": {"id": parent_status_id}
        }
        for i, child_id in enumerate(children_ids):
            child_id = int(child_id)
            child_status_id = int(children_status_ids[i])

            if parent_status_id == child_status_id:
                continue

            planfix_post(f"task/{child_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_work_from_children")
async def complete_work_from_children(request: web.Request):
    try:
        body = await request.json()

        work_task_id = int(body["work_task_id"])
        children_statuses = body["children_statuses"]
        is_order_work_task = bool(body["is_order_work_task"])
        order_task_id = int(body["order_task_id"])

        logging.info("\ncomplete_work_from_children")
        logging.info("work_task_id %d", work_task_id)
        logging.info("children_statuses %s", children_statuses)
        logging.info("is_order_work_task %s", "true" if is_order_work_task else "false")
        logging.info("order_task_id %d", order_task_id)

        all_complete = False
        for status_id in children_statuses:
            if int(status_id) != 224:  # Проверка наличия материалов
                all_complete = False
                break

            all_complete = True

        if all_complete is True:
            status = 2 if is_order_work_task else 224  # В работе/Проверка наличия материалов
            body = {
                "status": {"id": status}
            }
            planfix_post(f"task/{work_task_id}?silent=false", body)

            if is_order_work_task:
                planfix_post(f"task/{order_task_id}?silent=false", body)

            logging.info("Complete: status %d", status)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_work_from_children2")
async def complete_work_from_children2(request: web.Request):
    try:
        body = await request.json()

        work_task_id = int(body["work_task_id"])
        children_statuses = body["children_statuses"]

        logging.info("\ncomplete_work_from_children2")
        logging.info("work_task_id %d", work_task_id)
        logging.info("children_statuses %s", children_statuses)
        all_complete = False
        for status_id in children_statuses:
            if int(status_id) != 221:  # Подтверждение наличия материалов
                all_complete = False
                break

            all_complete = True

        if all_complete is True:
            status = 221  # Подтверждение наличия материалов
            body = {
                "status": {"id": status}
            }
            planfix_post(f"task/{work_task_id}?silent=false", body)

            logging.info("Complete: status %d", status)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_detail_work_from_cutting")
async def complete_detail_work_from_cutting(request: web.Request):
    try:
        body = await request.json()

        work_type_id = int(body["work_type_id"])
        detail_work_task_type_ids = body["detail_work_task_type_ids"][0].split(",")
        detail_work_task_ids = body["detail_work_task_ids"][0].split(",")

        logging.info("\ncomplete_detail_work_from_cutting")
        logging.info("work_type_id %d", work_type_id)
        logging.info("detail_work_task_type_ids %s", detail_work_task_type_ids)
        logging.info("detail_work_task_ids %s", detail_work_task_ids)

        for i, detail_work_type_id in enumerate(detail_work_task_type_ids):
            if int(detail_work_type_id) == work_type_id:
                body = {
                    "status": {"id": 3}  # Завершённая
                }
                planfix_post(f"task/{int(detail_work_task_ids[i])}?silent=false", body)
                logging.info(planfix_get(f"task/{int(detail_work_task_ids[i])}?fields=name&sourceId=0").json()["task"]["name"])

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_details_from_cutting")
async def complete_details_from_cutting(request: web.Request):
    try:
        body = await request.json()

        work_type_id = int(body["work_type_id"])
        work_type_ids = body["work_type_ids"][0].split(",")
        work_ids = body["work_ids"][0].split(",")

        logging.info("\ncomplete_details_from_cutting")
        logging.info("work_type_ids %s", work_type_ids)
        logging.info("work_ids %s", work_ids)

        for i, work_id in enumerate(work_ids):
            if int(work_type_ids[i]) == work_type_id:
                logging.info(planfix_get(f"task/{int(work_id)}?fields=name&sourceId=0").json()["task"]["name"])

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/accept_work_from_cutting")
async def accept_work_from_cutting(request: web.Request):
    try:
        body = await request.json()

        logging.info("\naccept_work_from_cutting")

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/create_cutting_from_work")
async def create_cutting_from_work(request: web.Request):
    try:
        body = await request.json()

        task_id = int(body["task_id"])
        work_name = body["work_name"]
        cutting_count = int(body["cutting_count"])

        logging.info("\ncreate_cutting_from_work")
        logging.info("task_id %d", task_id)
        logging.info("work_name %s", work_name)

        body = {
            "name": f"Раскрой листа №{cutting_count} {work_name}",
        }
        planfix_post(f"task/{task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/create_work_from_order")
async def create_work_from_order(request: web.Request):
    try:
        body = await request.json()

        order_id = int(body["order_id"])
        order_number = int(planfix_get(f"task/{order_id}?fields=105596&sourceId=0").json()["task"]["customFieldData"][0]["value"])
        details = body["details"]
        subtask_counts = body["subtask_counts"]

        logging.info("\ncreate_work_from_order")
        logging.info("order_id %d", order_id)
        logging.info("details (all subtasks) %s", details)
        logging.info("subtask_counts %s", subtask_counts)

        input_detail_ids = details[0]
        input_detail_templates = details[1]
        input_detail_cutting_needed = details[2]

        work_belongs_to_assembly = []
        for i in range(len(input_detail_ids)):
            work_belongs_to_assembly.append('Нет')
        work_belongs_to_order = []
        for i in range(len(input_detail_ids)):
            work_belongs_to_order.append('Нет')
        order_task_tree = recreate_task_tree_from_list(order_id, input_detail_ids, input_detail_templates, subtask_counts, input_detail_cutting_needed, work_belongs_to_assembly, work_belongs_to_order)
        order_task_tree.print_children()

        material_directory = planfix_post("directory/19/entry/list", {"offset": 0, "pageSize": 100, "fields": "key,33", "groupsOnly": False}).json()["directoryEntries"]
        material_name_to_id = {}
        for material_entry in material_directory:
            material_name = str(material_entry["customFieldData"][0]["value"]).upper()
            material_name_to_id[material_name] = material_entry["key"]

        unique_work_names = {}
        unique_work_cuttings_user_group = {}
        work_list = planfix_post(f"directory/14/entry/list", {"offset": 0, "pageSize": 100, "fields": "key,28,59", "groupsOnly": False}).json()["directoryEntries"]
        for work_entry in work_list:
            if "customFieldData" in work_entry:
                entry_id = int(work_entry["key"])
                unique_work_names[entry_id] = work_entry["customFieldData"][0]["value"]

                unique_work_cuttings_user_group[entry_id] = int(work_entry["customFieldData"][1]["value"]["id"].replace("group:", "")) if (work_entry["customFieldData"][1].keys().__contains__("value") and work_entry["customFieldData"][1]["value"] is not None) else -1

        reported_errors = []
        unique_work = {}
        for assembly_task in order_task_tree.children:
            for detail_task in assembly_task.children:
                for work_task in detail_task.children:
                    def get_work_error():
                        return f"\"{planfix_get(f"task/{detail_task.get_id()}?fields=name&sourceId=0").json()["task"]["name"]}\" [{unique_work_names[work_type]}] Ошибка: "

                    if work_task.cutting_needed:
                        task_data = planfix_get(f"task/{work_task.get_id()}?fields=105881,105574&sourceId=0").json()["task"]

                        work_type = int(task_data["customFieldData"][1]["value"]["id"])

                        # Retrieve detail information (Name, Files)
                        file_ids = task_data["customFieldData"][0]["value"]
                        # if len(file_ids) > 1:
                        #     reported_errors.append(get_work_error() + "Количество файлов DVG/DXF больше чем 1")
                        #     continue
                        if len(file_ids) == 0:
                            reported_errors.append(get_work_error() + "Нет файлов DVG/DXF")
                            continue

                        thickness = 0
                        material = ""
                        for file_id in file_ids:
                            # Sort details based on Thicknesses, Material
                            filename = planfix_get(f"file/{file_id}?fields=name").json()["file"]["name"]
                            filename = filename[0: filename.rfind(".")]

                            detail_data = parse_filename(filename)
                            if "error" in detail_data.keys():
                                reported_errors.append(get_work_error() + detail_data["error"])
                                continue

                            new_thickness = detail_data["thickness"]
                            new_material = str(detail_data["material"]).upper()

                            if thickness != 0 and thickness != new_thickness:
                                reported_errors.append(get_work_error() + f"Все толщины должны быть одинаковыми")
                                continue
                            thickness = new_thickness

                            if len(material) != 0 and material != new_material:
                                reported_errors.append(get_work_error() + f"Все материалы должны быть одинаковыми")
                                continue
                            material = new_material

                            if material not in material_name_to_id:
                                reported_errors.append(get_work_error() + f"Неизвестный материал \"{detail_data["material"]}\"")
                                continue

                            detail_task.dvg_file_ids.append(file_id)

                        if (work_type, thickness, material) not in unique_work:
                            unique_work[(work_type, thickness, material)] = []

                        unique_work[(work_type, thickness, material)].append(detail_task)

        if len(reported_errors) != 0:
            error_message = ""
            for i, error in enumerate(reported_errors):
                error_message += error
                if i < len(reported_errors) - 1:
                    error_message += "\n"

            body = {
                "status": {"id": 207},  # Конструкторский отдел
                "customFieldData": [
                    {
                        "field": {"id": 105921},  # Причина возврата на доработку
                        "value": "Ошибки в названии файлов. Подробнее смотреть \"Комментарий для доработки\""
                    },
                    {
                        "field": {"id": 105802},  # Комментарий для доработки
                        "value": error_message
                    },
                    {
                        "field": {"id": 105953},  # Возвращено на доработку
                        "value": get_list_field_values(14602, 105953)[0]
                    }
                ]
            }
            planfix_post(f"task/{order_id}?silent=false", body)
            logging.info(f"Errors found in order: {error_message}")
            return web.json_response({"code": 1, "error_message": error_message})

        work_order_task_id = 0
        if len(unique_work) != 0:  # We have work to do
            body = {
                "name": f"{planfix_get(f'task/{order_id}?fields=name&sourceId=0').json()['task']['name']} (Работа)",
                "status": {"id": 186},  # Вывод У.П.
                "processId": 77665,  # Вывод У.П.
                "template": {"id": 15155},  # Работа
                "customFieldData": [
                    {
                        "field": {"id": 105873},  # Заказ
                        "value": order_id
                    }
                ]
            }
            response = planfix_post("task/", body)
            work_order_task_id = int(response.json()["id"])

        body = {
            "customFieldData": [
                {
                    "field": {"id": 105971},  # Работа (Заказ/Сборка)
                    "value": work_order_task_id
                }
            ]
        }
        planfix_post(f"task/{order_id}?silent=false", body)

        for (work, thickness, material) in unique_work.keys():
            detail_ids = []
            file_ids = []
            cutting_user_group = -1
            for detail in unique_work[(work, thickness, material)]:
                detail_ids.append(detail.get_id())
                file_ids += detail.dvg_file_ids
                cutting_user_group = unique_work_cuttings_user_group[work]

            body = {
                "name": f"{unique_work_names[work]} {material}(Материал) {thickness}(Толщина) Работа({order_number})",
                "status": {
                    "id": 186  # Вывод У.П.
                },
                "processId": 77665,  # Вывод У.П.
                "template": {"id": 15155},  # Работа
                "parent": {"id": work_order_task_id},
                "customFieldData": [
                    {
                        "field": {"id": 105873},  # Заказ
                        "value": order_id
                    },
                    {
                        "field": {"id": 105881},  # Текущая Обработка
                        "value": work
                    },
                    {
                        "field": {"id": 105939},  # Детали
                        "value": detail_ids
                    },
                    {
                        "field": {"id": 106026}, # Неиспользованные детали
                        "value": detail_ids
                    },
                    {
                        "field": {"id": 105858},  # Толщина
                        "value": thickness
                    },
                    {
                        "field": {"id": 105889},  # Материал
                        "value": material_name_to_id[material]
                    },
                    {
                        "field": {"id": 105574},  # Файлы DWG/DXF
                        "value": file_ids
                    }
                ]
            }
            response = planfix_post("task/", body)
            work_task_id = int(response.json()["id"])

            if cutting_user_group != -1:
                work_task = planfix_get(f"task/{work_task_id}?fields=assignees&sourceId=0").json()["task"]
                assignees = {"users": [], "groups": []}
                if work_task.keys().__contains__("assignees"):
                    assignees = work_task["assignees"]

                old_user_list = []
                for user in assignees["users"]:
                    old_user_list.append({"id": "user:" + str(user["id"]).replace("user:", "")})
                old_group_list = []
                for group in assignees["groups"]:
                    old_group_list.append({"id": int(group["id"])})
                body = {
                    "assignees": {
                        "users": old_user_list,
                        "groups": old_group_list
                    }
                }

                if not old_group_list.__contains__(cutting_user_group):
                    body["assignees"]["groups"].append({"id": cutting_user_group})

                planfix_post(f"task/{work_task_id}?silent=false", body)

        return web.json_response({"code": 0})
    except Exception as e:
        print_error(e)
        return web.json_response({"code": 0})  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/create_work_from_assembly")
async def create_work_from_assembly(request: web.Request):
    try:
        body = await request.json()

        assembly_id = int(body["assembly_id"])
        assembly_name = body["assembly_name"]
        assembly_parent_id = int(body["assembly_parent_id"])
        order_id = int(body["order_id"])
        order_task = planfix_get(f"task/{order_id}?fields=name,105596,105971&sourceId=0").json()["task"]
        logging.info("order_task %s", order_task)
        order_name = order_task["name"]
        order_number = int(order_task["customFieldData"][1]["value"])
        order_work_task_id = int(order_task["customFieldData"][0]["value"]["id"] if order_task["customFieldData"][0]["value"] is not None else 0)
        details = body["details"]
        subtask_counts = body["subtask_counts"]
        work_belongs_to_assembly = body["work_belongs_to_assembly"]
        work_belongs_to_order = body["work_belongs_to_order"]

        logging.info("\ncreate_work_from_assembly")
        logging.info("assembly_id %d", assembly_id)
        logging.info("assembly_name %s", assembly_name)
        logging.info("assembly_parent_id %d", assembly_parent_id)
        logging.info("order_id %d", order_id)
        logging.info("details (all subtasks) %s", details)
        logging.info("subtask_counts %s", subtask_counts)
        logging.info("work_belongs_to_assembly %s", work_belongs_to_assembly)
        logging.info("work_belongs_to_order %s", work_belongs_to_order)

        if order_id != assembly_parent_id:
            logging.info("assembly task is not a direct child of the order task, skipping it")
            return web.HTTPOk()

        input_detail_ids = details[0]
        input_detail_templates = details[1]
        input_detail_cutting_needed = details[2]

        assembly_task_tree = recreate_task_tree_from_list(assembly_id, input_detail_ids, input_detail_templates, subtask_counts, input_detail_cutting_needed, work_belongs_to_assembly, work_belongs_to_order)
        assembly_task_tree.print_children()

        material_directory = planfix_post("directory/19/entry/list", {"offset": 0, "pageSize": 100, "fields": "key,33", "groupsOnly": False}).json()["directoryEntries"]
        material_name_to_id = {}
        for material_entry in material_directory:
            material_name = str(material_entry["customFieldData"][0]["value"]).upper()
            material_name_to_id[material_name] = material_entry["key"]

        unique_work_names = {}
        unique_work_cuttings_user_group = {}
        work_list = planfix_post(f"directory/14/entry/list", {"offset": 0, "pageSize": 100, "fields": "key,28,59", "groupsOnly": False}).json()["directoryEntries"]
        for work_entry in work_list:
            if "customFieldData" in work_entry:
                entry_id = int(work_entry["key"])
                unique_work_names[entry_id] = work_entry["customFieldData"][0]["value"]

                unique_work_cuttings_user_group[entry_id] = int(work_entry["customFieldData"][1]["value"]["id"].replace("group:", "")) if (work_entry["customFieldData"][1].keys().__contains__("value") and work_entry["customFieldData"][1]["value"] is not None) else -1

        reported_errors = []
        unique_work = {}
        for work_task in assembly_task_tree.get_all_children():
            if not work_task.is_work_task():
                continue

            detail_task = work_task.parent

            def get_work_error():
                return f"Сборка: \"{assembly_name}\" деталь: \"{planfix_get(f"task/{detail_task.get_id()}?fields=name&sourceId=0").json()["task"]["name"]}\" [{unique_work_names[work_type]}] Ошибка: "

            if work_task.cutting_needed:
                task_data = planfix_get(f"task/{work_task.get_id()}?fields=105881,105574&sourceId=0").json()["task"]

                work_type = int(task_data["customFieldData"][1]["value"]["id"])

                # Retrieve detail information (Name, Files)
                file_ids = task_data["customFieldData"][0]["value"]
                # if len(file_ids) > 1:
                #     reported_errors.append(get_work_error() + "Количество файлов DVG/DXF больше чем 1")
                #     continue
                if len(file_ids) == 0:
                    reported_errors.append(get_work_error() + "Нет файлов DVG/DXF")
                    continue

                thickness = 0
                material = ""
                for file_id in file_ids:
                    # Sort details based on Thicknesses, Material
                    filename = planfix_get(f"file/{file_id}?fields=name").json()["file"]["name"]
                    filename = filename[0: filename.rfind(".")]

                    detail_data = parse_filename(filename)
                    if "error" in detail_data.keys():
                        reported_errors.append(get_work_error() + detail_data["error"])
                        continue

                    new_thickness = detail_data["thickness"]
                    new_material = str(detail_data["material"]).upper()

                    if thickness != 0 and thickness != new_thickness:
                        reported_errors.append(get_work_error() + f"Все толщины должны быть одинаковыми")
                        continue
                    thickness = new_thickness

                    if len(material) != 0 and material != new_material:
                        reported_errors.append(get_work_error() + f"Все материалы должны быть одинаковыми")
                        continue
                    material = new_material

                    if material not in material_name_to_id:
                        reported_errors.append(get_work_error() + f"Неизвестный материал \"{detail_data["material"]}\"")
                        continue

                    detail_task.dvg_file_ids.append(file_id)

                if (work_type, thickness, material) not in unique_work:
                    unique_work[(work_type, thickness, material)] = []

                unique_work[(work_type, thickness, material)].append(detail_task)

        if len(reported_errors) != 0:
            error_message = ""
            for i, error in enumerate(reported_errors):
                error_message += error
                if i < len(reported_errors) - 1:
                    error_message += "\n"

            body = {
                "status": {"id": 207},  # Конструкторский отдел
                "customFieldData": [
                    {
                        "field": {"id": 105921},  # Причина возврата на доработку
                        "value": "Ошибки в названии файлов. Подробнее смотреть \"Комментарий для доработки\""
                    },
                    {
                        "field": {"id": 105802},  # Комментарий для доработки
                        "value": error_message
                    },
                    {
                        "field": {"id": 105953},  # Возвращено на доработку
                        "value": get_list_field_values(14602, 105953)[0]
                    }
                ]
            }
            planfix_post(f"task/{order_id}?silent=false", body)
            logging.info(f"Errors found in order: {error_message}")
            return web.json_response({"code": 1, "error_message": error_message})

        if len(unique_work) == 0:
            pass # TODO: Move assembly to work status
        else: # We have work to do
            if order_work_task_id == 0:
                body = {
                    "name": f"{order_name} Работа({order_number})",
                    "status": {"id": 186},  # Вывод У.П.
                    "processId": 77665,  # Вывод У.П.
                    "template": {"id": 15155},  # Работа
                    "customFieldData": [
                        {
                            "field": {"id": 105873},  # Заказ
                            "value": order_id
                        }
                    ]
                }
                response = planfix_post("task/", body)
                order_work_task_id = int(response.json()["id"])

                body = {
                    "customFieldData": [
                        {
                            "field": {"id": 105971}, # "Работа (Заказ/Сборка)
                            "value": order_work_task_id
                        }
                    ]
                }
                planfix_post(f"task/{order_id}?silent=false", body)

            body = {
                "name": f"{assembly_name} Работа({order_number})",
                "status": {"id": 186},  # Вывод У.П.
                "processId": 77665,  # Вывод У.П.
                "template": {"id": 15155},  # Работа
                "parent": {"id": order_work_task_id},
                "customFieldData": [
                    {
                        "field": {"id": 105873},  # Заказ
                        "value": order_id
                    },
                    {
                        "field": {"id": 106028},  # Сборка
                        "value": assembly_id
                    }
                ]
            }
            response = planfix_post("task/", body)
            assembly_work_task_id = int(response.json()["id"])

            body = {
                "customFieldData": [
                    {
                        "field": {"id": 105971},  # Работа (Заказ/Сборка)
                        "value": assembly_work_task_id
                    }
                ]
            }
            planfix_post(f"task/{assembly_id}?silent=false", body)

            for (work, thickness, material) in unique_work.keys():
                detail_ids = []
                file_ids = []
                cutting_user_group = -1
                for detail in unique_work[(work, thickness, material)]:
                    detail_ids.append(detail.get_id())
                    file_ids += detail.dvg_file_ids
                    cutting_user_group = unique_work_cuttings_user_group[work]

                body = {
                    "name": f"{unique_work_names[work]} {material}(Материал) {thickness}(Толщина) Работа({order_number})",
                    "status": {
                        "id": 186  # Вывод У.П.
                    },
                    "processId": 77665,  # Вывод У.П.
                    "template": {"id": 15155},  # Работа
                    "parent": {"id": assembly_work_task_id},
                    "customFieldData": [
                        {
                            "field": {"id": 105873},  # Заказ
                            "value": order_id
                        },
                        {
                            "field": {"id": 106028},  # Сборка
                            "value": assembly_id
                        },
                        {
                            "field": {"id": 105881},  # Текущая Обработка
                            "value": work
                        },
                        {
                            "field": {"id": 105939},  # Детали
                            "value": detail_ids
                        },
                        {
                            "field": {"id": 106026}, # Неиспользованные детали
                            "value": detail_ids
                        },
                        {
                            "field": {"id": 105858},  # Толщина
                            "value": thickness
                        },
                        {
                            "field": {"id": 105889},  # Материал
                            "value": material_name_to_id[material]
                        },
                        {
                            "field": {"id": 105574},  # Файлы DWG/DXF
                            "value": file_ids
                        }
                    ]
                }
                response = planfix_post("task/", body)
                work_task_id = int(response.json()["id"])

                if cutting_user_group != -1:
                    work_task = planfix_get(f"task/{work_task_id}?fields=assignees&sourceId=0").json()["task"]
                    assignees = {"users": [], "groups": []}
                    if work_task.keys().__contains__("assignees"):
                        assignees = work_task["assignees"]

                    old_user_list = []
                    for user in assignees["users"]:
                        old_user_list.append({"id": "user:" + str(user["id"]).replace("user:", "")})
                    old_group_list = []
                    for group in assignees["groups"]:
                        old_group_list.append({"id": int(group["id"])})
                    body = {
                        "assignees": {
                            "users": old_user_list,
                            "groups": old_group_list
                        }
                    }

                    if not old_group_list.__contains__(cutting_user_group):
                        body["assignees"]["groups"].append({"id": cutting_user_group})

                    planfix_post(f"task/{work_task_id}?silent=false", body)

        return web.json_response({"code": 0})
    except Exception as e:
        print_error(e)
        return web.json_response({"code": 0})  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_order")
async def complete_order(request: web.Request):
    try:
        body = await request.json()

        main_task_id = int(body["main_task_id"])
        subtask_ids = body["subtask_ids"]
        subtask_status_ids = body["subtask_status_ids"]

        logging.info("\ncomplete_order")
        logging.info("main_task_id %d", main_task_id)
        logging.info("subtask_ids %s", subtask_ids)
        logging.info("subtask_status_ids %s", subtask_status_ids)

        all_subtasks_complete = True
        process_ids = []
        for i in range(len(subtask_status_ids)):
            task_id = int(subtask_ids[i])
            status_id = int(subtask_status_ids[i])
            process_id = int(planfix_get(f"task/{task_id}?fields=processId&sourceId=0").json()["task"]["processId"])
            process_ids.append(process_id)

            if process_id == 77659:  # Складское хозяйство
                pass
            else:
                if status_id != 3 and status_id != 189:  # Завершенная/Готово
                    all_subtasks_complete = False
                    break
        logging.info("_process_ids %s", process_ids)

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing order")

            body = {
                "processId": 77659,  # Складское хозяйство
                "status": {"id": 189}  # Готово
            }
            planfix_post(f"task/{main_task_id}?silent=false", body)

            for i, task_id in enumerate(subtask_ids):
                if process_ids[i] == 77663:  # Производство
                    body = {
                        "processId": 77659,  # Складское хозяйство
                        "status": {"id": 189}  # Готово
                    }
                    planfix_post(f"task/{int(task_id)}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_assembly_from_work")
async def complete_assembly_from_work(request: web.Request):
    try:
        body = await request.json()

        task_id = int(body["task_id"])
        parent_task_first_level_assembly = True if int(body["parent_task_first_level_assembly"]) == 1 else False
        subtask_statuses = body["subtask_statuses"]
        order_assembly_work_count = int(str(body["order_assembly_work_count"]) if len(str(body["order_assembly_work_count"])) != 0 else 0)

        logging.info("\ncomplete_assembly_from_work")
        logging.info("task_id %d", task_id)
        logging.info("parent_task_first_level_assembly %s", "true" if parent_task_first_level_assembly else "false")
        logging.info("subtask_statuses %s", subtask_statuses)
        logging.info("order_assembly_work_count %d", order_assembly_work_count)

        all_subtasks_complete = True
        for i in range(len(subtask_statuses)):
            status_id = int(subtask_statuses[i])

            if status_id != 3:  # Завершенная
                all_subtasks_complete = False

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing parent task")

            if parent_task_first_level_assembly and order_assembly_work_count == 0:
                body = {
                    "status": {"id": 189}  # Готово
                }
            else:
                body = {
                    "status": {"id": 3}  # Завершенная
                }

            planfix_post(f"task/{task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_detail_from_work")
async def complete_detail_from_work(request: web.Request):
    try:
        body = await request.json()

        task_id = int(body["task_id"])
        subtask_statuses = body["subtask_statuses"]

        logging.info("\ncomplete_detail_from_work")
        logging.info("task_id %d", task_id)
        logging.info("subtask_statuses %s", subtask_statuses)

        all_subtasks_complete = True
        for i in range(len(subtask_statuses)):
            status_id = int(subtask_statuses[i])

            if status_id != 3:  # Завершенная
                all_subtasks_complete = False

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing parent task")

            body = {
                "status": {"id": 3}  # Завершенная
            }
            planfix_post(f"task/{task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/complete_assembly_from_details")
async def complete_assembly_from_details(request: web.Request):
    try:
        body = await request.json()

        task_id = int(body["task_id"])
        subtask_statuses = body["subtask_statuses"]
        is_first_level_assembly = int(body["is_first_level_assembly"]) == 1

        logging.info("\ncomplete_assembly_from_details")
        logging.info("task_id %d", task_id)
        logging.info("subtask_statuses %s", subtask_statuses)
        logging.info("is_first_level_assembly %s", "true" if is_first_level_assembly else "false")

        all_subtasks_complete = True
        for i in range(len(subtask_statuses)):
            status_id = int(subtask_statuses[i])

            if status_id != 3:  # Завершенная
                all_subtasks_complete = False

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing parent task")

            complete_status = 3 # Завершенная
            if is_first_level_assembly:
                complete_status = 189 # Готово

            body = {
                "status": {"id": complete_status}
            }
            planfix_post(f"task/{task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/add_confirmation_people")
async def add_confirmation_people(request: web.Request):
    try:
        body = await request.json()

        main_task_id = int(body["main_task_id"])
        confirmation_needed = str(body["confirmation_needed"])
        confirmation_needed = re.sub(r":\s*,", ": [],", confirmation_needed)
        confirmation_needed = eval(confirmation_needed)

        logging.info("\nadd_confirmation_people")
        logging.info("main_task_id %d", main_task_id)
        logging.info("confirmation_needed %s", confirmation_needed)

        main_task = planfix_get(f"task/{main_task_id}?fields=id,name,assignees&sourceId=0").json()["task"]

        old_user_list = []
        for user in main_task["assignees"]["users"]:
            old_user_list.append({"id": "user:" + str(user["id"]).replace("user:", "")})
        old_group_list = []
        for group in main_task["assignees"]["groups"]:
            old_group_list.append({"id": int(group["id"])})
        body = {
            "assignees": {
                "users": old_user_list,
                "groups": old_group_list
            },
            "customFieldData": []
        }

        update_task = False

        # Сварка
        welding_confirmation_group = 47145
        welding = confirmation_needed["welding"]
        for work in welding:
            if work == "Да":
                welding_confirmation_field = 105917

                if not old_group_list.__contains__(welding_confirmation_group):
                    body["assignees"]["groups"].append({"id": welding_confirmation_group})

                body["customFieldData"].append(
                    {
                        "field": {
                            "id": welding_confirmation_field
                        },
                        "value": get_list_field_values(14602, welding_confirmation_field)[0]
                    }
                )
                update_task = True
                break

        # Токарные работы
        turning_work_confirmation_group = 47147
        turning_work = confirmation_needed["turning_work"][0].split(",") if len(confirmation_needed["turning_work"]) != 0 else []
        for work in turning_work:
            if work == "Да":
                turning_work_confirmation_field = 105919

                if not old_group_list.__contains__(turning_work_confirmation_group):
                    body["assignees"]["groups"].append({"id": turning_work_confirmation_group})

                body["customFieldData"].append(
                    {
                        "field": {
                            "id": turning_work_confirmation_field
                        },
                        "value": get_list_field_values(14602, turning_work_confirmation_field)[0]
                    }
                )
                update_task = True
                break

        if update_task:
            logging.info("confirmation needed, adding confirmation people")
            planfix_post(f"task/{main_task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/check_material_completeness")
async def check_material_completeness(request: web.Request):
    try:
        body = await request.json()

        main_task_id = int(body["main_task_id"])
        tasks_materials = body["tasks_materials"]

        logging.info("\ncheck_material_completeness")
        logging.info("main_task_id %d", main_task_id)
        logging.info("tasks_materials %s", tasks_materials)

        all_materials_found = True
        for i in range(len(tasks_materials[0][0].split(","))):
            status_id = int(tasks_materials[0][0].split(",")[i])
            template_id = int(tasks_materials[1][0].split(",")[i])

            if template_id == 8732005:  # Деталь
                if status_id == 220:  # Перемещение материалов
                    all_materials_found = False

        if all_materials_found:
            logging.info("All materials found")

            body = {
                "status": {"id": 221},  # Подтверждение наличия материалов
                "customFieldData": [
                    {
                        "field": {"id": 105905},  # Перемещение материалов
                        "value": ""
                    }
                ]
            }
            planfix_post(f"task/{main_task_id}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


@routes.post("/create_work_tasks_from_parent_task")
async def create_work_tasks_from_parent_task(request: web.Request):
    try:
        body = await request.json()

        order_id = int(body["order_id"])
        task_id = int(body["task_id"])
        work_to_order = body["work_to_order"]  # Типы обработки
        is_assembly = bool(body["is_assembly"])
        is_order = bool(body["is_order"])

        logging.info("\ncreate_work_tasks_from_parent_task")
        logging.info("task_id %d", task_id)
        logging.info("work_to_order %s", work_to_order)
        logging.info("is_assembly %s", "true" if is_assembly else "false")
        logging.info("is_order %s", "true" if is_order else "false")

        tasks_to_turn_into_draft = []

        is_first = True
        for i in range(len(work_to_order[0])):
            turn_task_to_draft = False

            if is_assembly and not is_order:
                body = {
                    "status": {"id": 207},  # Конструкторский отдел
                    "processId": 77663,  # Производство
                    "customFieldData": [
                        {
                            "field": {"id": 105931},  # Текущая Обработка (Сборка)
                            "value": {"id": int(work_to_order[0][i])}
                        },
                        {
                            "field": {"id": 105945},  # Работа для сборки
                            "value": True
                        }
                    ]
                }
                turn_task_to_draft = True
            elif not is_assembly and not is_order:
                body = {
                    "status": {"id": 207},  # Конструкторский отдел
                    "processId": 77657,  # Конструкторский отдел и Раскрой
                    "customFieldData": [
                        {
                            "field": {"id": 105881},  # Текущая Обработка
                            "value": {"id": int(work_to_order[0][i])}
                        }
                    ]
                }

                if is_first:
                    parent_body = {
                        "customFieldData": body["customFieldData"]
                    }
                    planfix_post(f"task/{task_id}?silent=false", parent_body)

                if not is_first:
                    turn_task_to_draft = True
            elif not is_assembly and is_order:
                body = {
                    "status": {"id": 207},  # Конструкторский отдел
                    "processId": 77663,  # Производство
                    "customFieldData": [
                        {
                            "field": {"id": 105931},  # Текущая Обработка (Сборка)
                            "value": {"id": int(work_to_order[0][i])}
                        },
                        {
                            "field": {"id": 105945},  # Работа для сборки
                            "value": False
                        },
                        {
                            "field": {"id": 105949},  # Работа для заказа
                            "value": True
                        }
                    ]
                }
                turn_task_to_draft = True
            else:
                raise Exception(f"Unhandled work_creation from: is_assembly={is_assembly}, is_order={is_order}")

            body["name"] = work_to_order[1][i]
            body["template"] = {"id": 14510}  # Обработка
            body["parent"] = {"id": task_id}
            body["customFieldData"].append({
                "field": {"id": 105873},  # Заказ
                "value": order_id
            })
            response = planfix_post("task/", body)
            if turn_task_to_draft:
                tasks_to_turn_into_draft.append(int(response.json()["id"]))

            is_first = False

        for task_to_draft in tasks_to_turn_into_draft:
            body = {
                "status": {"id": 0}  # Черновик
            }
            planfix_post(f"task/{task_to_draft}?silent=false", body)

        return web.HTTPOk()
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


output_directory = os.path.abspath("resources/tmp")
dxf_generator = DXFGenerator(output_directory)
igs_generator = IGSGenerator(output_directory)


@routes.post("/create_typical_parts")
async def create_typical_parts(request: web.Request):
    try:
        body = await request.json()

        analitics = body["analitics"]
        number = body["number"]
        author = body["author"]

        output_dxf_parts = []
        output_pdf_parts = []
        output_igs_parts = []

        for analitic in analitics:
            part_thickness = 0
            part_count = 0
            part_name = ""
            part_type = None
            tube_type = None
            part_material = ""

            rect_width = 0
            rect_height = 0

            circle_diameter = 0

            circle_hole_diameter = 0

            tube_length = 0

            technical_path = ""

            for field in analitic["data"]:
                match field["name"]:
                    case "Толщина(мм)":
                        try:
                            part_thickness = float(field["value"])
                        except Exception as e:
                            print_error(e)
                            part_thickness = 0.0
                    case "Количество":
                        try:
                            part_count = int(field["value"])
                        except Exception as e:
                            print_error(e)
                            part_count = 0
                    case "Название детали":
                        part_name = field["value"]
                    case "Материал":
                        part_material = field["value"]

                    case "Ширина(мм)":
                        try:
                            rect_width = float(field["value"])
                        except Exception as e:
                            print_error(e)
                            rect_width = 0.0
                    case "Высота(мм)":
                        try:
                            rect_height = float(field["value"])
                        except Exception as e:
                            print_error(e)
                            rect_height = 0.0

                    case "Диаметр(мм)":
                        try:
                            circle_diameter = float(field["value"])
                        except Exception as e:
                            print_error(e)
                            circle_diameter = 0.0

                    case "Диаметр отверстия(мм)":
                        try:
                            circle_hole_diameter = float(field["value"])
                        except Exception as e:
                            print_error(e)
                            circle_hole_diameter = 0.0

                    case "Длина(мм)":
                        try:
                            tube_length = float(field["value"])
                        except Exception as e:
                            print_error(e)
                            tube_length = 0.0

                    case "Технологический маршрут":
                        technical_path = field["value"]

                    case _:
                        print_error("Unknown filed: %s" % field["name"])

            if len(author) == 0:
                print_error("Part author must not be empty")
                return web.json_response({"code": 1, "message": "Автор деталей не может быть пустым", "dxf_files": [], "pdf_files": []})
            if number == 0:
                print_error("Part number width must not be 0")
                return web.json_response({"code": 1, "message": "Номер заказа не может быть пустым", "dxf_files": [], "pdf_files": []})

            if len(part_material) == 0:
                print_error("Part material must not be empty")
                return web.json_response({"code": 1, "message": "Неизвестный материал детали", "dxf_files": [], "pdf_files": []})
            if len(technical_path) == 0:
                print_error("Part technical_path must not be empty")
                return web.json_response({"code": 1, "message": "Технологический маршрут не может быть пустым", "dxf_files": [], "pdf_files": []})

            if part_count == 0:
                print_error("Part count must not be 0")
                return web.json_response({"code": 1, "message": "Количество деталей должно быть больше 0", "dxf_files": [], "pdf_files": []})

            if len(part_name) == 0:
                print_error("Part name must not be empty")
                return web.json_response({"code": 1, "message": "Название детали не может быть пустым", "dxf_files": [], "pdf_files": []})

            filepath = part_name
            match analitic["analitic"]["name"]:
                case "Типовая деталь [Прямоугольник]":
                    if len(part_name) == 0:
                        part_name = "Прямоугольник"
                    part_type = DXFGenerator.PartType.Rect
                    filepath = part_name + (
                            (f" {part_thickness:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{rect_height:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{rect_width:.10f}".rstrip('0').rstrip('.')) +
                            f"_{part_material}_{part_count}шт")
                case "Типовая деталь [Косынка]":
                    if len(part_name) == 0:
                        part_name = "Косынка"
                    part_type = DXFGenerator.PartType.Triangle
                    filepath = part_name + (
                            (f" {part_thickness:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{rect_height:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{rect_width:.10f}".rstrip('0').rstrip('.')) +
                            f"_{part_material}_{part_count}шт")
                case "Типовая деталь [Круг]":
                    if len(part_name) == 0:
                        part_name = "Круг"
                    part_type = DXFGenerator.PartType.Circle
                    filepath = part_name + (
                            (f" {part_thickness:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{circle_diameter:.10f}".rstrip('0').rstrip('.')) +
                            f"_{part_material}_{part_count}шт")
                case "Типовая деталь [Шайба]":
                    if len(part_name) == 0:
                        part_name = "Шайба"
                    part_type = DXFGenerator.PartType.CircleWithHole
                    filepath = part_name + (
                            (f" {part_thickness:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{circle_diameter:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{circle_hole_diameter:.10f}".rstrip('0').rstrip('.')) +
                            f"_{part_material}_{part_count}шт")
                case "Труба [Круг]":
                    tube_type = IGSGenerator.TubeType.Circle
                    filepath = part_name + (
                            (f" {circle_diameter:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{part_thickness:.10f}".rstrip('0').rstrip('.')) +
                            (f"_{tube_length:.10f}".rstrip('0').rstrip('.') + "мм") +
                            f"_{part_material}_{part_count}шт").replace(",", ".")
                case "Труба [Прямоугольник]":
                    tube_type = IGSGenerator.TubeType.Rectangle
                    filepath = part_name + (
                            (f" {rect_width:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{rect_height:.10f}".rstrip('0').rstrip('.')) +
                            (f"x{part_thickness:.10f}".rstrip('0').rstrip('.')) +
                            (f"_{tube_length:.10f}".rstrip('0').rstrip('.') + "мм") +
                            f"_{part_material}_{part_count}шт").replace(",", ".")

            if tube_type is None:
                if part_thickness == 0:
                    print_error("Part thickness must not be 0")
                    return web.json_response({"code": 1, "message": "Толщина деталей должна быть больше 0", "dxf_files": [], "pdf_files": []})

                if len(filepath) == 0:
                    filepath = part_name

                if part_type is None:
                    print_error("Part type must not be null")
                    return web.json_response({"code": 1, "message": "Неизвестный тип детали", "dxf_files": [], "pdf_files": []})

                dxf_generator.reset(part_thickness, part_count, part_name, filepath, author, number, part_material,
                                    technical_path)
                match part_type:
                    case DXFGenerator.PartType.Rect:
                        if rect_width == 0:
                            print_error("Rect width must not be 0")
                            return web.json_response({"code": 1, "message": "Ширина прямоугольника должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        if rect_height == 0:
                            print_error("Rect height must not be 0")
                            return web.json_response({"code": 1, "message": "Высота прямоугольника должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        dxf_generator.generate_rect(Vec2(0, 0), Vec2(rect_width, rect_height))

                    case DXFGenerator.PartType.Triangle:
                        if rect_width == 0:
                            print_error("Triangle width must not be 0")
                            return web.json_response({"code": 1, "message": "Ширина косынки должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        if rect_height == 0:
                            print_error("Triangle height must not be 0")
                            return web.json_response({"code": 1, "message": "Высота косынки должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        dxf_generator.generate_triangle(Vec2(0, 0), Vec2(rect_width, rect_height))

                    case DXFGenerator.PartType.Circle:
                        if circle_diameter == 0:
                            print_error("Circle diameter must not be 0")
                            return web.json_response({"code": 1, "message": "Диаметр круга должен быть больше 0", "dxf_files": [], "pdf_files": []})
                        dxf_generator.generate_circle(Vec2(0, 0), circle_diameter)

                    case DXFGenerator.PartType.CircleWithHole:
                        if circle_diameter == 0:
                            print_error("Circle with hole: diameter must not be 0")
                            return web.json_response({"code": 1, "message": "Диаметр шайбы должен быть больше 0", "dxf_files": [], "pdf_files": []})
                        if circle_hole_diameter == 0:
                            print_error("Circle with hole: hole diameter must not be 0")
                            return web.json_response({"code": 1, "message": "Диаметр отверстия шайбы должен быть больше 0", "dxf_files": [], "pdf_files": []})
                        dxf_generator.generate_circle_with_hole(Vec2(0, 0), circle_diameter, circle_hole_diameter)

                    case _:
                        print_error("Unknown partType: %s" % part_type)
                        return web.json_response({"code": 1, "message": "Неизвестный тип детали", "dxf_files": [], "pdf_files": []})

                dxf_filepath, pdf_filepath = dxf_generator.save()

                files = [
                    ('file', (dxf_filepath.split("\\")[-1], open(dxf_filepath, 'rb'), 'application/binary'))
                ]
                headers = {
                    'Accept': 'application/json',
                    "Authorization": f"Bearer {BEARER_TOKEN}"
                }
                response = requests.request("POST", f"{BASE_URL}file/", headers=headers, files=files)
                output_dxf_parts.append(response.json()["id"])

                files = [
                    ('file', (pdf_filepath.split("\\")[-1], open(pdf_filepath, 'rb'), 'application/pdf'))
                ]
                headers = {
                    'Accept': 'application/json',
                    "Authorization": f"Bearer {BEARER_TOKEN}"
                }
                response = requests.request("POST", f"{BASE_URL}file/", headers=headers, files=files)
                output_pdf_parts.append(response.json()["id"])
            else:
                igs_generator.reset(filepath)
                tube_type_name = ""
                match tube_type:
                    case IGSGenerator.TubeType.Circle:
                        tube_type_name = "Труба круглая"
                    case IGSGenerator.TubeType.Rectangle:
                        tube_type_name = "Труба профильная"

                dxf_generator.reset(part_thickness, part_count, f"{tube_type_name} | {part_name}", f"{tube_type_name} {filepath}", author, number, part_material, technical_path)

                match tube_type:
                    case IGSGenerator.TubeType.Circle:
                        if circle_diameter == 0:
                            print_error("Circle diameter must not be 0")
                            return web.json_response({"code": 1, "message": "Внешний диаметр круглой трубы должен быть больше 0", "dxf_files": [], "pdf_files": []})
                        if part_thickness == 0:
                            print_error("Thickness must not be 0")
                            return web.json_response({"code": 1, "message": "Толщина круглой трубы должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        if tube_length == 0:
                            print_error("Tube length must not be 0")
                            return web.json_response({"code": 1, "message": "Длина круглой трубы должна быть больше 0", "dxf_files": [], "pdf_files": []})

                        igs_generator.generate_circle_tube(circle_diameter, part_thickness, tube_length)

                        dxf_generator.generate_rect(Vec2(0, 0), Vec2(tube_length, circle_diameter))
                        dxf_generator.generate_circle_with_hole(Vec2(tube_length + circle_diameter * 3, circle_diameter / 2), circle_diameter, circle_diameter - part_thickness * 2)

                    case IGSGenerator.TubeType.Rectangle:
                        if rect_width == 0:
                            print_error("Rect width must not be 0")
                            return web.json_response({"code": 1, "message": "Ширина прямоугольной трубы должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        if rect_height == 0:
                            print_error("Rect height must not be 0")
                            return web.json_response({"code": 1, "message": "Высота прямоугольной трубы должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        if part_thickness == 0:
                            print_error("Thickness must not be 0")
                            return web.json_response({"code": 1, "message": "Толщина прямоугольной трубы должна быть больше 0", "dxf_files": [], "pdf_files": []})
                        if tube_length == 0:
                            print_error("Tube length must not be 0")
                            return web.json_response({"code": 1, "message": "Длина прямоугольной трубы должна быть больше 0", "dxf_files": [], "pdf_files": []})

                        igs_generator.generate_rect_tube(rect_width, rect_height, part_thickness, tube_length)

                        dxf_generator.generate_rect(Vec2(0, 0), Vec2(tube_length, rect_height))
                        dxf_generator.generate_rect_with_hole(Vec2(tube_length + rect_height * 3, 0),
                                                              Vec2(rect_width, rect_height),
                                                              Vec2(rect_width - part_thickness * 2,
                                                                   rect_height - part_thickness * 2))

                tube_filepath = igs_generator.save()

                files = [
                    ('file', (tube_filepath.split("\\")[-1], open(tube_filepath, 'rb'), 'application/binary'))
                ]
                headers = {
                    'Accept': 'application/json',
                    "Authorization": f"Bearer {BEARER_TOKEN}"
                }
                response = requests.request("POST", f"{BASE_URL}file/", headers=headers, files=files)
                output_igs_parts.append(response.json()["id"])

                dxf_filepath, pdf_filepath = dxf_generator.save()  # Ignoring dxf files because tubes just wants igs and pdf files

                files = [
                    ('file', (pdf_filepath.split("\\")[-1], open(pdf_filepath, 'rb'), 'application/pdf'))
                ]
                headers = {
                    'Accept': 'application/json',
                    "Authorization": f"Bearer {BEARER_TOKEN}"
                }
                response = requests.request("POST", f"{BASE_URL}file/", headers=headers, files=files)
                output_pdf_parts.append(response.json()["id"])

        clean_tmp_files()

        output_json = {"code": 0, "message": "Ok", "dxf_files": output_dxf_parts, "pdf_files": output_pdf_parts, "igs_files": output_igs_parts}
        logging.info(output_json)
        return web.json_response(output_json)
    except Exception as e:
        print_error(e)
        return web.HTTPOk()  # Planfix will sleep for 3 minutes if it receives error code, so always return 200


def main():
    logging.info("\033[32m====================================================\033[0m")
    logging.info("\033[35m(PlanfixZTTA)\033[32m  ---Program start---\033[0m")
    logging.info("\033[32m====================================================\033[0m")

    # clean_dwg_files()
    # clean_tmp_files()
    #
    # start_converter()

    app.add_routes(routes)

    cors = aiohttp_cors.setup(app)

    for route in list(app.router.routes()):
        cors.add(route, {"https://ztta.planfix.kg": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*")})

    while True:
        try:
            # ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            # ssl_context.check_hostname = False
            # ssl_context.load_cert_chain('/etc/letsencrypt/live/ztta.planfix_app.kg/fullchain.pem', '/etc/letsencrypt/live/ztta.planfix_app.kg/privkey.pem')

            aiohttp.web.run_app(app, host=HOST, port=PORT)  # , ssl_context=ssl_context)
        except Exception as e:
            print_error(e)
            sleep(15)


if __name__ == "__main__":
    main()
