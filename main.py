import os
import re
from time import sleep

import aiohttp
from aiohttp import web
import aiohttp_cors

from igs_generator.igs_generator import IGSGenerator
from planfix_api import *
from base import *
import requests
# from converter import convert_to_pdf, clean_dwg_files, clean_tmp_files
from dxf_generator.dxf_generator import DXFGenerator
from structs import *

import logging


USER_GROUP__WELDING_CONFIRMATION = 47145  # Одобряют (Сварку)
USER_GROUP__TURING_WORK_CONFIRMATION = 47147  # Одобряют (Токарные работы)

PROCESS__CONSTRUCTORS = 77657  # Конструкторский отдел
PROCESS__CUTTING = 77665  # Вывод У.П.
PROCESS__PRODUCTION = 77663  # Производство
PROCESS__WAREHOUSING = 77659  # Складское хозяйство

STATUS__IN_WORK = 2  # В работе
STATUS__CONSTRUCTORS = 207  # Конструкторский отдел
STATUS__IN_QUEUE = 237  # В очереди
STATUS__CUTTING = 186  # Вывод У.П.
STATUS__CONFIRMATION = 185  # Согласование
STATUS__MOVEMENT_BETWEEN_DEPARTMENTS = 217  # Перемещение между подразделениями
STATUS__ACCEPT_WORK = 228  # Принять работу
STATUS__MATERIAL_EXISTENCE_CHECKING = 224  # Проверка наличия материалов
STATUS__MATERIAL_EXISTENCE_CONFIRMATION = 221  # Подтверждение наличия материалов
STATUS__MATERIAL_MOVEMENT = 220  # Перемещение материалов
STATUS__COMPLETE = 3  # Завершённая
STATUS__READY = 189  # Готово

# Sending template id from Planfix sends this values
PLANFIX_TEMPLATE__ASSEMBLY = 8732191  # Сборка
PLANFIX_TEMPLATE__DETAIL = 8732005  # Деталь
PLANFIX_TEMPLATE__PROCESSING = 8732007  # Обработка
# Getting template id via Planfix rest API gives this values, and this values should be used to send template id to Planfix rest API
REST_API_TEMPLATE__ASSEMBLY = 14602  # Сборка
REST_API_TEMPLATE__DETAIL = 14509  # Деталь
REST_API_TEMPLATE__PROCESSING = 14510  # Обработка
REST_API_TEMPLATE__WORK = 15155  # Работа

FIELD__REVISION_CAUSE = 105921  # Причина возврата на доработку
FIELD__REVISION_COMMENT = 105802  # Комментарий для доработки
FIELD__RETURNED_TO_REVISION = 105953  # Возвращено на доработку
FIELD__CURRENT_WORK_TYPE = 105881  # Текущая Обработка
FIELD__CURRENT_WORK_TYPE_ASSEMBLY = 105931  # Текущая Обработка (Сборка)
FIELD__WORK_FOR_ASSEMBLY = 105945  # Работа для сборки [Костыль]
FIELD__WORK_FOR_ORDER = 105949  # Работа для заказа [Костыль]
FIELD__DELETE_TASK = 105947  # Удалить задачу
FIELD__FILES_ARE_CHECKED = 106034  # Файлы проверены
FIELD__CUTTING_NEEDED = 106040  # Нужно создавать раскрои
FIELD__WORK_ORDER_OR_ASSEMBLY = 105971  # Работа (Заказ/Сборка)
FIELD__ORDER = 105873  # Заказ
FIELD__ORDER_TYPE_COMMERCIAL = 105869  # Тип заказа (Коммерческий)
FIELD__ORDER_TYPE_INNER = 105885  # Тип заказа (Внутренний)
FIELD__ORDER_NUMBER = 105596  # Номер заказа
FIELD__WORK_FILES = 106042  # Файлы работы
FIELD__DRAWING_FILES = 105871  # Чертежи PDF
FIELD__CUTTING_COST_CALCULATIONS_FILES = 105925  # Просчёт (PDF)
FIELD__PROCESSING_TYPES = 105879  # Типы обработки
FIELD__PROCESSING_TYPES_ASSEMBLY = 105929  # Типы обработки (Сборка)
FIELD__MATERIAL = 105889  # Материал
FIELD__THICKNESS = 105858  # Толщина
FIELD__UNUSED_DETAILS = 106026  # Неиспользованные детали
FIELD__DETAILS = 105939  # Детали
FIELD__ASSEMBLY = 106028  # Сборка
FIELD__ACCEPT_WORK = 105967  # Принять работу
FIELD__MATERIAL_MOVEMENT = 105905  # Перемещение материалов
FIELD__WELDING_CONFIRMATION = 105917  # Согласование (Сварки)
FIELD__TURING_WORK_CONFIRMATION = 105919  # Согласование (Токарных работ)

DIRECTORY__MATERIAL_SHEET = 19  # Материал (Лист)
DIRECTORY__MATERIAL_SHEET__FIELD__NAME = 33  # Название

DIRECTORY__PROCESSING_TYPE = 14  # Тип обработки
DIRECTORY__PROCESSING_TYPE__FIELD__NAME = 28  # Название
DIRECTORY__PROCESSING_TYPE__FIELD__CUTTING_PEOPLE = 59  # Раскройщик

DIRECTORY__PROCESSING_TYPES_ASSEMBLY = 25  # Тип обработки (Сборка)
DIRECTORY__PROCESSING_TYPES_ASSEMBLY__FIELD__WELDING_CONFIRMATION_NEEDED = 53  # Согласование сварки

HTML_COLOR_ERROR = "#E74C3C"
HTML_COLOR_ACCENT = "#CC00CC"


class PlanfixOk(web.HTTPOk):
    status_code = 200


class PlanfixError(web.HTTPOk):  # Planfix will sleep for 3 minutes if it receives error code, so always return success
    status_code = 200


HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 10210))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

routes = web.RouteTableDef()
app = aiohttp.web.Application()
tmp_dir = os.path.abspath("resources/tmp")

output_directory = os.path.abspath("resources/tmp")
dxf_generator = DXFGenerator(output_directory)
igs_generator = IGSGenerator(output_directory)


def get_parent_main_assembly(task_id):
    task_data = {}
    parent_task = -1

    while ("customFieldData" not in task_data or not task_data["customFieldData"][0]["value"]) and task_id != -1:
        task_data = planfix_get(f"task/{task_id}?fields=parent,106030&sourceId=0").json()["task"]
        if "customFieldData" not in task_data or not task_data["customFieldData"][0]["value"]:
            parent_task = int(task_data["parent"]["id"]) if "parent" in task_data else -1
            task_id = parent_task

    return parent_task


def send_assembly_to_revision(assembly_id, reported_errors, revision_cause):
    error_message = ""
    max_index_length = len(str(len(reported_errors) + 1))
    for i, error in enumerate(reported_errors):
        error_message += f'<p><span style="white-space:&nbsp;pre-wrap;">{i + 1}){"&nbsp;&nbsp;" * (max_index_length - len(str(i + 1)))}&nbsp;</span>{error}</p>'
        if i < len(reported_errors) - 1:
            error_message += "\n"

    body = {
        "status": {"id": STATUS__CONSTRUCTORS},
        "processId": PROCESS__CONSTRUCTORS,
        "customFieldData": [
            {
                "field": {"id": FIELD__REVISION_CAUSE},
                "value": revision_cause
            },
            {
                "field": {"id": FIELD__REVISION_COMMENT},
                "value": error_message
            },
            {
                "field": {"id": FIELD__RETURNED_TO_REVISION},
                "value": get_list_field_values(REST_API_TEMPLATE__ASSEMBLY, FIELD__RETURNED_TO_REVISION)[0]
            }
        ]
    }
    planfix_post(f"task/{assembly_id}?silent=false", body)
    logging.info(f"Errors found in assembly:\n{error_message}")
    return error_message


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
    filename_format = filename_format.replace("assembly_id", "Номер/Название сборки")
    filename_format = filename_format.replace("detail_id", "Номер/Название детали")
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
    filespan = filename[0: filename.rfind(".")]
    components = filespan.split("_")

    if len(components) < 3:
        # if len(components) < 6:
        print_error(f"Filename \"{filename}\" incorrectly formatted. Format is \"{filename_format}\"")
        return {"error": f"Неверный формат названия файла: \"{filename}\". Корректный формат: \"{filename_format_to_ru(filename_format)}\""}

    # try:
    #     order_number = int(components[0])
    # except Exception as e:
    #     print_error(f"{components[0]} Incorrect format for OrderNumber. Error is: {e}")
    #     return {"error": f"(Номер заказа) Неверный формат: {components[0]}"}

    # try:
    #     assembly_id = int(components[1])
    # except Exception as e:
    #     print_error(f"{components[1]} Incorrect format for AssemblyID. Error is: {e}")
    #     return {"error": f"(Номер сборки) Неверный формат: {components[1]}"}

    # try:
    #     detail_id = int(components[2])
    # except Exception as e:
    #     print_error(f"{components[2]} Incorrect format for DetailID. Error is: {e}")
    #     return {"error": f"(Номер детали) Неверный формат: {components[2]}"}
    detail_id = components[0]

    # material = components[3]
    material = components[1]
    # if material not in material_table:
    #     print_error(f"{material} Unknown material")
    #     return {"error": f"(Материал) Неизвестный Материал: {material}"}

    # try:
    #     thickness = int(components[4])
    # except Exception as e:
    #     print_error(f"{components[4]} Incorrect format for Thickness. Error is: {e}")
    #     return {"error": f"(Толщина) Неверный формат: {components[4]}"}
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
    #     return {"error": f"(Количество) Неверный формат: {components[5]}"}

    return {
        # "order_number": order_number,
        # "assembly_id": assembly_id,
        "detail_id": detail_id,
        "material": material,
        "thickness": thickness  # ,
        # "quantity": quantity
    }


class Task:
    def __init__(self, task_id: int, template_id: int, status_id: int):
        self.task_id = task_id
        self.template_id = template_id
        self.status_id = status_id
        self.cutting_needed = None
        self.work_belongs_to_assembly = None
        self.work_belongs_to_order = None

        self.parent = None
        self.children = []

        self.work_file_ids = []

    def get_id(self):
        return self.task_id

    def get_parent_id(self):
        if self.parent:
            return self.parent.get_id()

        return -1

    def is_assembly_task(self):
        return self.template_id == PLANFIX_TEMPLATE__ASSEMBLY

    def is_detail_task(self):
        return self.template_id == PLANFIX_TEMPLATE__DETAIL

    def is_work_task(self):
        return self.template_id == PLANFIX_TEMPLATE__PROCESSING

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
            f"{'  ' * level}{self.task_id}[{self.template_id}]({self.status_id}){' cutting' if self.cutting_needed else ''}{' assembly_work' if self.work_belongs_to_assembly else ''}{' order_work' if self.work_belongs_to_order else ''}")  # planfix_get(f"task/{self._id}?fields=name&sourceId=0").json()["task"]["name"]
        level += 1
        for child in self.children:
            child.print_children(level)

    def __str__(self):
        return str(self.task_id)


# TODO: This is not the best solution, we should just use parent task id's with children task id's instead of all of this template, children count nonsense
def recreate_task_tree_from_list(root_task_id, root_task_template_id, root_task_status_id, task_ids, template_ids, subtask_counts, cutting_needed, work_belongs_to_assembly, work_belongs_to_order, task_status_ids):
    tasks = [Task(int(tid), int(tmpl_id), int(st_id)) for tid, tmpl_id, st_id in zip(task_ids, template_ids, task_status_ids)]
    root = Task(root_task_id, root_task_template_id, root_task_status_id)

    index = 0
    sub_index = 0
    leaf_counter = 0
    current_work_counter = 0

    def parse_subtree():
        nonlocal index, sub_index, leaf_counter, current_work_counter
        start_index = index  # <- define here!

        task = tasks[index]
        index += 1

        if task.template_id == PLANFIX_TEMPLATE__PROCESSING:
            # Leaf node, no descendants
            task.cutting_needed = cutting_needed[current_work_counter] == "Да"
            task.work_belongs_to_assembly = work_belongs_to_assembly[leaf_counter] == "Да"
            task.work_belongs_to_order = work_belongs_to_order[leaf_counter] == "Да"
            leaf_counter += 1
            current_work_counter += 1
            return task
        elif task.template_id == PLANFIX_TEMPLATE__DETAIL:
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


def assembly_needs_revision(assembly_process_id, assembly_status_id):
    match assembly_process_id:
        case process_id if process_id == PROCESS__PRODUCTION:
            return True

        case process_id if process_id == PROCESS__CONSTRUCTORS:
            if assembly_status_id != STATUS__CONSTRUCTORS:
                return True

    return False


def field_changed_send_assembly_to_revision(field_name, current_user, current_time, revision_cause_task_id):
    assembly_id = get_parent_main_assembly(revision_cause_task_id)
    logging.info("assembly_id: %d", assembly_id)
    if assembly_id == -1:
        assembly_id = revision_cause_task_id

    assembly_data = planfix_get(f"task/{assembly_id}?fields=name,status,processId&sourceId=0").json()["task"]
    assembly_process_id = assembly_data["processId"]
    assembly_status_id = assembly_data["status"]["id"]

    if assembly_needs_revision(assembly_process_id, assembly_status_id):
        revision_cause_task_data = planfix_get(f"task/{revision_cause_task_id}?fields=name,template,parent&sourceId=0").json()["task"]
        revision_cause_task_parent_id = revision_cause_task_data["parent"]["id"]
        revision_cause_task_parent_name = planfix_get(f"task/{revision_cause_task_parent_id}?fields=name&sourceId=0").json()["task"]["name"]
        revision_cause_task_template_id = revision_cause_task_data["template"]["id"]

        cause_task_path = ''
        match revision_cause_task_template_id:
            case template_id if template_id == REST_API_TEMPLATE__PROCESSING:
                cause_task_path += (f'<a href="https://ztta.planfix.com/task/{revision_cause_task_parent_id}">{revision_cause_task_parent_name}</a>' +
                                    ' &rarr; ' +
                                    f'<a href="https://ztta.planfix.com/task/{revision_cause_task_id}">{revision_cause_task_data["name"]}</a>')
            case _:
                cause_task_path += f'<a href="https://ztta.planfix.com/task/{revision_cause_task_id}">{revision_cause_task_data["name"]}</a>'

        error_message = (cause_task_path +
                         ': ' +
                         f'<span style="color: {HTML_COLOR_ERROR};">Изменено значение поля</span> "{field_name}"')

        send_assembly_to_revision(assembly_id, [error_message],
                                  f'{current_user} ' +
                                  'в ' +
                                  f'<span style="color: {HTML_COLOR_ACCENT};">{current_time}</span> ' +
                                  f'<span style="color: {HTML_COLOR_ERROR};">вернул на доработку</span> ' +
                                  'из ' +
                                  f'<span style="color: {HTML_COLOR_ACCENT};">"{assembly_data["status"]["name"]}"</span>\n' +
                                  'Причину смотреть в "Комментарий для доработки"')


@routes.post("/field_changed_send_assembly_to_revision")
async def field_changed_send_assembly_to_revision_(request: web.Request):
    try:
        body = await request.json()

        task_id = int(body["task_id"])
        current_user = body["current_user"]
        current_time = body["current_time"]
        field_name = body["field_name"]

        logging.info("\nfield_changed_send_assembly_to_revision")
        logging.info("task_id %d", task_id)
        logging.info("current_user %s", current_user)
        logging.info("current_time %s", current_time)
        logging.info("field_name %s", field_name)

        field_changed_send_assembly_to_revision(field_name, current_user, current_time, task_id)
        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/reset_order_work_field_when_all_assemblies_in_constructor_process")
async def reset_order_work_field_when_all_assemblies_in_constructor_process(request: web.Request):
    try:
        body = await request.json()

        order_id = int(body["order_id"])
        sub_task_ids = list(map(int, body["sub_task_ids"]))

        logging.info("\nreset_order_work_field_when_all_assemblies_in_constructor_process")
        logging.info("order_id %d", order_id)
        logging.info("sub_task_ids %s", sub_task_ids)

        all_tasks_in_constructor_process = True
        for sub_task_id in sub_task_ids:
            sub_task_data = planfix_get(f"task/{sub_task_id}?fields=processId,status&sourceId=0").json()["task"]

            if sub_task_data["processId"] != PROCESS__CONSTRUCTORS:
                all_tasks_in_constructor_process = False
                break
            if sub_task_data["status"]["id"] != STATUS__CONSTRUCTORS and sub_task_data["status"]["id"] != STATUS__CONFIRMATION:
                all_tasks_in_constructor_process = False
                break

        if all_tasks_in_constructor_process:
            body = {
                "customFieldData": [
                    {
                        "field": {"id": FIELD__WORK_ORDER_OR_ASSEMBLY},
                        "value": {"id": 0}
                    }
                ]
            }
            planfix_post(f"task/{order_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/update_work_tasks_or_send_assembly_to_revision")
async def update_work_tasks_or_send_assembly_to_revision(request: web.Request):
    try:
        body = await request.json()

        detail_id = int(body["detail_id"])
        order_id = int(body["order_id"])
        work_type_ids = list(map(int, body["work_type_ids"]))
        work_type_names = body["work_type_names"]
        sub_task_work_type_ids = list(map(int, body["sub_task_work_type_ids"]))
        sub_task_work_type_names = body["sub_task_work_type_names"]
        sub_task_work_ids = list(map(int, body["sub_task_work_ids"]))

        logging.info("\nupdate_work_tasks_or_send_assembly_to_revision")
        logging.info("detail_id %d", detail_id)
        logging.info("order_id %d", order_id)
        logging.info("work_type_ids %s", work_type_ids)
        logging.info("work_type_names %s", work_type_names)
        logging.info("sub_task_work_type_ids %s", sub_task_work_type_ids)
        logging.info("sub_task_work_type_names %s", sub_task_work_type_names)
        logging.info("sub_task_work_ids %s", sub_task_work_ids)

        old_dict = dict(zip(sub_task_work_type_ids, sub_task_work_type_names))
        new_ids_set = set(work_type_ids)
        removed_work_types = [
            {"work_type_id": id_, "work_type_name": name, "task_id": task_id}
            for id_, name, task_id in zip(sub_task_work_type_ids, sub_task_work_type_names, sub_task_work_ids)
            if id_ not in new_ids_set
        ]
        new_dict = dict(zip(work_type_ids, work_type_names))
        added_work_types = [
            {"work_type_id": id_, "work_type_name": new_dict[id_]}
            for id_ in work_type_ids
            if id_ not in old_dict
        ]
        logging.info("removed: %s", removed_work_types)
        logging.info("added:   %s", added_work_types)

        for removed_work in removed_work_types:
            body = {
                "customFieldData": [
                    {
                        "field": {"id": FIELD__DELETE_TASK},
                        "value": True
                    }
                ]
            }
            planfix_post(f"task/{removed_work["task_id"]}?silent=false", body)

        for added_work in added_work_types:
            body = {
                "status": {"id": STATUS__CONSTRUCTORS},
                "processId": PROCESS__CONSTRUCTORS,
                "template": REST_API_TEMPLATE__PROCESSING,
                "parent": {"id": detail_id},
                "name": added_work["work_type_name"],
                "customFieldData": [
                    {
                        "field": {"id": FIELD__CURRENT_WORK_TYPE},
                        "value": added_work["work_type_id"]
                    },
                    {
                        "field": {"id": FIELD__ORDER},
                        "value": order_id
                    }
                ],
            }
            planfix_post(f"task", body)

        to_remove = [{"work_type_id": item["work_type_id"], "work_type_name": item["work_type_name"]} for item in removed_work_types]
        kept = [{"work_type_id": item[0], "work_type_name": item[1]} for item in zip(sub_task_work_type_ids, sub_task_work_type_names) if {"work_type_id": item[0], "work_type_name": item[1]} not in to_remove]
        final_list = kept + added_work_types
        new_first = final_list[0] if final_list else {"work_type_id": -1, "work_type_name": ""}
        logging.info("new_first: %s", new_first)

        body = {
            "customFieldData": [
                {
                    "field": {"id": FIELD__CURRENT_WORK_TYPE},
                    "value": new_first["work_type_id"]
                }
            ],
        }
        planfix_post(f"task/{detail_id}?silent=false", body)
        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/validate_files_in_assembly_and_create_work")
async def validate_files_in_assembly_and_create_work(request: web.Request):
    try:
        body = await request.json()

        create_work_tasks = body["create_work_tasks"] == "Да"
        assembly_id = int(body["assembly_id"])
        assembly_name = body["assembly_name"]
        order_id = int(body["order_id"])
        order_task = planfix_get(f"task/{order_id}?fields=name,{FIELD__ORDER_NUMBER},{FIELD__WORK_ORDER_OR_ASSEMBLY},{FIELD__ORDER_TYPE_COMMERCIAL},{FIELD__ORDER_TYPE_INNER}&sourceId=0").json()["task"]
        logging.info("order_task %s", order_task)
        order_name = order_task["name"]
        order_number = order_task["customFieldData"][2]["value"]
        order_type_inner_or_commercial = order_task["customFieldData"][1]
        order_work_task_id = int(order_task["customFieldData"][0]["value"]["id"] if "value" in order_task["customFieldData"][0] and order_task["customFieldData"][0]["value"] is not None else 0)
        is_order_commercial = order_type_inner_or_commercial["field"]["id"] == FIELD__ORDER_TYPE_COMMERCIAL

        sub_task_ids = list(map(int, body["sub_task_ids"]))
        sub_task_template_ids = list(map(int, body["sub_task_template_ids"]))
        sub_task_counts = list(map(int, str(body["sub_task_counts"]).split(",")))
        sub_task_cutting_needed = body["sub_task_cutting_needed"] if len(str(body["sub_task_cutting_needed"])) > 0 else []

        assembly_cost_calculation_files = list(map(int, body["assembly_cost_calculation_files"])) if len(str(body["assembly_cost_calculation_files"])) > 0 else []
        assembly_drawing_files = list(map(int, body["assembly_drawing_files"])) if len(str(body["assembly_drawing_files"])) > 0 else []
        assembly_needs_welding_confirmation = list([item == "Да" for item in body["assembly_needs_welding_confirmation"]]) if len(str(body["assembly_needs_welding_confirmation"])) > 0 else []

        logging.info("\nvalidate_files_in_assembly_and_create_work")
        logging.info("create_work_tasks %s", "true" if create_work_tasks else "false")
        logging.info("assembly_id %d", assembly_id)
        logging.info("assembly_name %s", assembly_name)
        logging.info("order_id %d", order_id)
        logging.info("order_name %s", order_name)
        logging.info("order_number %s", order_number)
        logging.info("is_order_commercial %s", "true" if is_order_commercial else "false")
        logging.info("order_work_task_id %d", order_work_task_id)
        logging.info("----------------------------------------")
        logging.info("sub_task_ids %s", sub_task_ids)
        logging.info("sub_task_template_ids %s", sub_task_template_ids)
        logging.info("sub_task_counts %s", sub_task_counts)
        logging.info("sub_task_cutting_needed %s", sub_task_cutting_needed)
        logging.info("----------------------------------------")
        logging.info("assembly_cost_calculation_files %s", assembly_cost_calculation_files)
        logging.info("assembly_drawing_files %s", assembly_drawing_files)
        logging.info("assembly_needs_welding_confirmation %s", assembly_needs_welding_confirmation)

        _tmp = []
        _tmp2 = []
        for i in range(len(sub_task_ids)):
            _tmp.append("Нет")
            _tmp2.append(-1)
        parent_task_tree = recreate_task_tree_from_list(assembly_id, 0, -1, sub_task_ids, sub_task_template_ids, sub_task_counts, sub_task_cutting_needed, _tmp, _tmp, _tmp2)
        parent_task_tree.print_children()

        task_names = {}

        def get_task_name(task_id):
            if task_id in task_names:
                return task_names[task_id]

            task_names[task_id] = planfix_get(f"task/{task_id}?fields=name&sourceId=0").json()["task"]["name"]
            return task_names[task_id]

        material_directory = planfix_post(f"directory/{DIRECTORY__MATERIAL_SHEET}/entry/list", {"offset": 0, "pageSize": 100, "fields": f"key,{DIRECTORY__MATERIAL_SHEET__FIELD__NAME}", "groupsOnly": False}).json()["directoryEntries"]
        material_name_to_id = {}
        for material_entry in material_directory:
            material_name = str(material_entry["customFieldData"][0]["value"]).upper()
            material_name_to_id[material_name] = material_entry["key"]

        unique_work_names = {}
        unique_work_cuttings_user_group = {}
        work_list = planfix_post(f"directory/{DIRECTORY__PROCESSING_TYPE}/entry/list", {"offset": 0, "pageSize": 100, "fields": f"key,{DIRECTORY__PROCESSING_TYPE__FIELD__NAME},{DIRECTORY__PROCESSING_TYPE__FIELD__CUTTING_PEOPLE}", "groupsOnly": False}).json()["directoryEntries"]
        for work_entry in work_list:
            if "customFieldData" in work_entry:
                entry_id = int(work_entry["key"])
                unique_work_names[entry_id] = work_entry["customFieldData"][0]["value"]

                unique_work_cuttings_user_group[entry_id] = int(work_entry["customFieldData"][1]["value"]["id"].replace("group:", "")) if ("value" in work_entry["customFieldData"][1].keys() and work_entry["customFieldData"][1]["value"] is not None) else -1

        has_missing_files = False
        has_wrong_file_names = False

        unique_cutting_work = {}
        checked_tasks = []
        reported_errors = []
        has_subassemblies = False
        for sub_task in parent_task_tree.get_all_children():
            if sub_task.get_id() in checked_tasks:
                continue

            checked_tasks.append(sub_task.get_id())
            match sub_task.template_id:
                case template_id if template_id == PLANFIX_TEMPLATE__ASSEMBLY:
                    has_subassemblies = True

                    task_data = planfix_get(f"task/{sub_task.task_id}?fields={FIELD__DRAWING_FILES},{FIELD__CUTTING_COST_CALCULATIONS_FILES},{FIELD__PROCESSING_TYPES_ASSEMBLY}&sourceId=0").json()["task"]

                    cost_calculation_files = task_data["customFieldData"][0]["value"]
                    assembly_work_types = task_data["customFieldData"][1]["value"]
                    drawing_files = task_data["customFieldData"][2]["value"]

                    assembly_welding_confirmation_needed = False
                    for work_type in assembly_work_types:
                        work_welding_confirmation_needed = planfix_get(f"directory/{DIRECTORY__PROCESSING_TYPES_ASSEMBLY}/entry/{work_type["id"]}?fields={DIRECTORY__PROCESSING_TYPES_ASSEMBLY__FIELD__WELDING_CONFIRMATION_NEEDED}").json()["entry"]["customFieldData"][0]["value"]
                        if work_welding_confirmation_needed:
                            assembly_welding_confirmation_needed = True
                            break

                    if is_order_commercial and len(cost_calculation_files) == 0:
                        reported_errors.append(f'<a href="https://ztta.planfix.com/task/{sub_task.get_id()}">{get_task_name(sub_task.get_id())}</a>' +
                                               ': ' +
                                               f'<span style="color:{HTML_COLOR_ERROR};">Нет файлов простчёта</span>')
                        has_missing_files = True

                    if assembly_welding_confirmation_needed and len(drawing_files) == 0:
                        reported_errors.append(f'<a href="https://ztta.planfix.com/task/{sub_task.get_id()}">{get_task_name(sub_task.get_id())}</a>' +
                                               ': ' +
                                               f'<span style="color:{HTML_COLOR_ERROR};">Нет файлов чертежей</span>')
                        has_missing_files = True

                case template_id if template_id == PLANFIX_TEMPLATE__PROCESSING:
                    task_data = planfix_get(f"task/{sub_task.task_id}?fields={FIELD__DRAWING_FILES},{FIELD__CURRENT_WORK_TYPE},{FIELD__WORK_FILES}&sourceId=0").json()["task"]

                    drawing_files = task_data["customFieldData"][0]["value"]
                    work_type = int(task_data["customFieldData"][1]["value"]["id"])
                    work_files = task_data["customFieldData"][2]["value"]

                    def add_work_error(message):
                        reported_errors.append(f'<a href="https://ztta.planfix.com/task/{sub_task.get_parent_id()}">{get_task_name(sub_task.get_parent_id())}</a>'
                                               ' &rarr; ' +
                                               f'<a href="https://ztta.planfix.com/task/{sub_task.get_id()}">{get_task_name(sub_task.get_id())}</a>' +
                                               ': ' +
                                               f'<span style="color:{HTML_COLOR_ERROR};">{message}</span>')

                    work_files_is_missing = False
                    if sub_task.cutting_needed:
                        if len(work_files) == 0:
                            add_work_error("Нет файлов работы")
                            has_missing_files = True
                            work_files_is_missing = True

                    if len(drawing_files) == 0:
                        add_work_error("Нет файлов чертежей")
                        has_missing_files = True

                    detail_task = sub_task.parent
                    if sub_task.cutting_needed and not work_files_is_missing:
                        # Retrieve detail information (Name, Files)
                        # if len(work_files) > 1:
                        #     add_work_error("Количество файлов DVG/DXF больше чем 1")
                        #     continue

                        thickness = 0
                        material = ""
                        for file_id in work_files:
                            # Sort details based on Thicknesses, Material
                            filename = planfix_get(f"file/{file_id}?fields=name").json()["file"]["name"]

                            detail_data = parse_filename(filename)
                            if "error" in detail_data.keys():
                                add_work_error(detail_data["error"])
                                has_wrong_file_names = True
                                continue

                            new_thickness = detail_data["thickness"]
                            new_material = str(detail_data["material"]).upper()

                            if thickness != 0 and thickness != new_thickness:
                                add_work_error("Все толщины должны быть одинаковыми")
                                has_wrong_file_names = True
                                continue
                            thickness = new_thickness

                            if len(material) != 0 and material != new_material:
                                add_work_error("Все материалы должны быть одинаковыми")
                                has_wrong_file_names = True
                                continue
                            material = new_material

                            if material not in material_name_to_id:
                                add_work_error(f"Неизвестный материал \"{detail_data["material"]}\"")
                                has_wrong_file_names = True
                                continue

                            detail_task.work_file_ids.append(file_id)

                        if (work_type, thickness, material) not in unique_cutting_work:
                            unique_cutting_work[(work_type, thickness, material)] = []

                        unique_cutting_work[(work_type, thickness, material)].append(detail_task)

        if not has_subassemblies:
            if is_order_commercial and len(assembly_cost_calculation_files) == 0:
                reported_errors.append(f'<a href="https://ztta.planfix.com/task/{assembly_id}">{get_task_name(assembly_id)}</a>' +
                                       ': ' +
                                       f'<span style="color:{HTML_COLOR_ERROR};">Нет файлов простчёта</span>')
                has_missing_files = True
        if True in assembly_needs_welding_confirmation:
            if len(assembly_drawing_files) == 0:
                reported_errors.append(f'<a href="https://ztta.planfix.com/task/{assembly_id}">{get_task_name(assembly_id)}</a>' +
                                       ': ' +
                                       f'<span style="color:{HTML_COLOR_ERROR};">Нет файлов чертежей</span>')
                has_missing_files = True

        if len(reported_errors) != 0:
            error_causes = []

            if has_missing_files:
                error_causes.append(f'<span style="color:{HTML_COLOR_ERROR};">Недостающие файлы</span>')
                pass
            if has_wrong_file_names:
                error_causes.append(f'<span style="color:{HTML_COLOR_ERROR};">Ошибки в названии файлов</span>')
                pass

            error_cause = ''
            for i, cause in enumerate(error_causes):
                error_cause += cause
                if i < len(error_causes) - 1:
                    error_cause += " и "

            error_cause += ' Подробнее смотреть "Комментарий для доработки"'

            error_message = send_assembly_to_revision(assembly_id, reported_errors, error_cause)
            return web.json_response({"code": 1, "error_message": error_message})

        logging.info("all files valid, sending task %d to %s", assembly_id, "cutting" if create_work_tasks else "confirmation")

        if create_work_tasks:
            if len(unique_cutting_work) == 0:
                body = {
                    "status": {
                        "id": STATUS__IN_WORK
                    }
                }
                planfix_post(f"task/{assembly_id}?silent=false", body)
            else:  # We have work to do
                if order_work_task_id == 0:
                    body = {
                        "name": f"{order_name} Работа({order_number})",
                        "status": {"id": STATUS__CUTTING},
                        "processId": PROCESS__CUTTING,
                        "template": {"id": REST_API_TEMPLATE__WORK},
                        "customFieldData": [
                            {
                                "field": {"id": FIELD__ORDER},
                                "value": order_id
                            }
                        ]
                    }
                    response = planfix_post("task/", body)
                    order_work_task_id = int(response.json()["id"])

                    body = {
                        "customFieldData": [
                            {
                                "field": {"id": FIELD__WORK_ORDER_OR_ASSEMBLY},
                                "value": order_work_task_id
                            }
                        ]
                    }
                    planfix_post(f"task/{order_id}?silent=true", body)

                body = {
                    "name": f"{assembly_name} Работа({order_number})",
                    "status": {"id": STATUS__CUTTING},
                    "processId": PROCESS__CUTTING,
                    "template": {"id": REST_API_TEMPLATE__WORK},
                    "parent": {"id": order_work_task_id},
                    "customFieldData": [
                        {
                            "field": {"id": FIELD__ORDER},
                            "value": order_id
                        },
                        {
                            "field": {"id": FIELD__ASSEMBLY},
                            "value": assembly_id
                        }
                    ]
                }
                response = planfix_post("task/", body)
                assembly_work_task_id = int(response.json()["id"])

                body = {
                    "customFieldData": [
                        {
                            "field": {"id": FIELD__WORK_ORDER_OR_ASSEMBLY},
                            "value": assembly_work_task_id
                        }
                    ]
                }
                planfix_post(f"task/{assembly_id}?silent=true", body)

                for (work, thickness, material) in unique_cutting_work.keys():
                    detail_ids = []
                    file_ids = []
                    cutting_user_group = -1
                    for detail in unique_cutting_work[(work, thickness, material)]:
                        detail_ids.append(detail.get_id())
                        file_ids += detail.work_file_ids
                        cutting_user_group = unique_work_cuttings_user_group[work]

                    body = {
                        "name": f"{unique_work_names[work]} {material}(Материал) {thickness}(Толщина) Работа({order_number})",
                        "status": {"id": STATUS__CUTTING},
                        "processId": PROCESS__CUTTING,
                        "template": {"id": REST_API_TEMPLATE__WORK},
                        "parent": {"id": assembly_work_task_id},
                        "customFieldData": [
                            {
                                "field": {"id": FIELD__ORDER},
                                "value": order_id
                            },
                            {
                                "field": {"id": FIELD__ASSEMBLY},
                                "value": assembly_id
                            },
                            {
                                "field": {"id": FIELD__CURRENT_WORK_TYPE},
                                "value": work
                            },
                            {
                                "field": {"id": FIELD__DETAILS},
                                "value": detail_ids
                            },
                            {
                                "field": {"id": FIELD__UNUSED_DETAILS},
                                "value": detail_ids
                            },
                            {
                                "field": {"id": FIELD__THICKNESS},
                                "value": thickness
                            },
                            {
                                "field": {"id": FIELD__MATERIAL},
                                "value": material_name_to_id[material]
                            },
                            {
                                "field": {"id": FIELD__WORK_FILES},
                                "value": file_ids
                            }
                        ]
                    }
                    response = planfix_post("task/", body)
                    work_task_id = int(response.json()["id"])

                    if cutting_user_group != -1:
                        work_task = planfix_get(f"task/{work_task_id}?fields=assignees&sourceId=0").json()["task"]
                        assignees = {"users": [], "groups": []}
                        if "assignees" in work_task.keys():
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

                        if cutting_user_group not in old_group_list:
                            body["assignees"]["groups"].append({"id": cutting_user_group})

                        planfix_post(f"task/{work_task_id}?silent=false", body)
        else:
            body = {
                "customFieldData": [
                    {
                        "field": {"id": FIELD__FILES_ARE_CHECKED},
                        "value": True
                    }
                ]
            }
            if len(unique_cutting_work) != 0:
                body["customFieldData"].append({
                    "field": {"id": FIELD__CUTTING_NEEDED},
                    "value": True
                })

            planfix_post(f"task/{assembly_id}?silent=true", body)

        return web.json_response({"code": 0})
    except Exception as e:
        print_error(e)
        return web.json_response({"code": 1, "error_message": e})  # Planfix will sleep for 3 minutes if it receives error code, so always return success


# When one task goes to status "Завершённая", moves next task in status "В очереди" to status passed by parameter "status_id"
@routes.post("/change_task_status_when_previous_in_wait_goes_to_complete")
async def change_task_status_when_previous_in_wait_goes_to_complete(request: web.Request):
    try:
        body = await request.json()

        task_id = int(body["task_id"])
        parent_id = int(body["parent_id"])
        neighbor_ids = body["neighbor_ids"]
        neighbor_template_ids = body["neighbor_template_ids"]
        neighbor_counts = body["neighbor_counts"]
        if type(neighbor_counts) == list and len(neighbor_counts) > 0 and type(neighbor_counts[0]) == list:
            neighbor_counts = []
        neighbor_task_status_ids = body["neighbor_task_status_ids"]
        status_id = int(body["status_id"])

        logging.info("\nchange_task_status_when_previous_in_wait_goes_to_complete")
        logging.info("task_id %d", task_id)
        logging.info("parent_id %d", parent_id)
        logging.info("sub_task_ids %s", neighbor_ids)
        logging.info("neighbor_template_ids %s", neighbor_template_ids)
        logging.info("neighbor_counts %s", neighbor_counts)
        logging.info("neighbor_task_status_ids %s", neighbor_task_status_ids)
        logging.info("status_id %d", status_id)

        _tmp = []
        for i in range(len(neighbor_ids)):
            _tmp.append("Нет")
        parent_task_tree = recreate_task_tree_from_list(parent_id, 0, -1, neighbor_ids, neighbor_template_ids, neighbor_counts, _tmp, _tmp, _tmp, neighbor_task_status_ids)
        parent_task_tree.print_children()

        all_neighbors_complete = True
        past_current_task = False
        next_task_id = 0
        for neighbor_task in parent_task_tree.children:
            if past_current_task:
                if neighbor_task.status_id == STATUS__IN_QUEUE:
                    next_task_id = neighbor_task.task_id
                    break

            if neighbor_task.status_id != STATUS__COMPLETE:
                all_neighbors_complete = False
                break

            if neighbor_task.task_id == task_id:
                past_current_task = True

        logging.info("all_neighbors_complete %s", "true" if all_neighbors_complete else "false")
        logging.info("next_task_id %d", next_task_id)

        if not all_neighbors_complete or next_task_id == 0:
            return PlanfixOk()

        body = {
            "status": {"id": status_id}
        }
        planfix_post(f"task/{next_task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/change_work_status_to_work_or_wait_for_work")
async def change_work_status_to_work_or_wait_for_work(request: web.Request):
    try:
        body = await request.json()

        assembly_id = int(body["assembly_id"])
        sub_task_ids = body["sub_task_ids"]
        sub_task_template_ids = body["sub_task_template_ids"]
        subtask_counts = str(body["subtask_counts"]).split(",")

        logging.info("\nchange_work_status_to_work_or_wait_for_work")
        logging.info("assembly_id %d", assembly_id)
        logging.info("sub_task_ids %s", sub_task_ids)
        logging.info("sub_task_template_ids %s", sub_task_template_ids)
        logging.info("subtask_counts %s", subtask_counts)

        _tmp = []
        _tmp2 = []
        for i in range(len(sub_task_ids)):
            _tmp.append("Нет")
            _tmp2.append(-1)
        task_tree = recreate_task_tree_from_list(assembly_id, PLANFIX_TEMPLATE__ASSEMBLY, -1, sub_task_ids, sub_task_template_ids, subtask_counts, _tmp, _tmp, _tmp, _tmp2)
        task_tree.print_children()

        for task in task_tree.get_all_children():
            match task.template_id:
                case template_id if template_id == PLANFIX_TEMPLATE__ASSEMBLY:
                    body = {
                        "status": {"id": STATUS__IN_WORK}
                    }
                    planfix_post(f"task/{task.task_id}?silent=false", body)

                case template_id if template_id == PLANFIX_TEMPLATE__DETAIL:
                    body = {
                        "status": {"id": STATUS__IN_WORK}
                    }
                    planfix_post(f"task/{task.task_id}?silent=false", body)

                    is_first = True
                    for work_task in task.children:
                        body = {
                            "status": {"id": STATUS__IN_QUEUE}
                        }
                        if is_first:
                            body["status"]["id"] = STATUS__ACCEPT_WORK
                            body["customFieldData"] = [
                                {
                                    "field": {"id": FIELD__ACCEPT_WORK},
                                    "value": get_list_field_values(REST_API_TEMPLATE__PROCESSING, FIELD__ACCEPT_WORK)[0]
                                }
                            ]

                        planfix_post(f"task/{work_task.task_id}?silent=false", body)
                        is_first = False

                case template_id if template_id == PLANFIX_TEMPLATE__PROCESSING:
                    if task.parent.template_id == PLANFIX_TEMPLATE__ASSEMBLY:
                        body = {
                            "status": {"id": STATUS__IN_QUEUE}
                        }
                        planfix_post(f"task/{task.task_id}?silent=false", body)

                case template_id if template_id == PLANFIX_TEMPLATE__PROCESSING:
                    pass

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
            return PlanfixOk()

        body = {
            "status": {"id": subtask_status_id}
        }
        planfix_post(f"task/{order_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
                    "field": {"id": FIELD__UNUSED_DETAILS},
                    "value": result
                }
            ]
        }
        planfix_post(f"task/{work_task_id}?silent=true", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/set_current_work_to_parent_and_movement_between_departments")
async def set_current_work_to_parent_and_movement_between_departments(request: web.Request):
    try:
        body = await request.json()

        if str(body["current_work_id"]) == '':
            return PlanfixOk()

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

        current_work_group_id = int(planfix_get(f"directory/{DIRECTORY__PROCESSING_TYPE}/entry/{current_work_id}?fields=parentKey").json()["entry"]["parentKey"])
        previous_work_group_id = int(planfix_get(f"directory/{DIRECTORY__PROCESSING_TYPE}/entry/{previous_work_id}?fields=parentKey").json()["entry"]["parentKey"])

        logging.info("current_work_group_id %d", current_work_group_id)
        logging.info("previous_work_group_id %d", previous_work_group_id)

        if current_work_group_id != previous_work_group_id:
            body = {
                "customFieldData": [
                    {
                        "field": {"id": FIELD__CURRENT_WORK_TYPE},
                        "value": {"id": current_work_id}
                    }
                ],
                "status": {"id": STATUS__MOVEMENT_BETWEEN_DEPARTMENTS}
            }
            planfix_post(f"task/{parent_task_id}?silent=false", body)

            for i, work_task_id_str in enumerate(work_task_ids):
                work_task_id = int(work_task_id_str)
                work_task_status_id = int(work_task_status_ids[i])

                if work_task_status_id == STATUS__IN_WORK:
                    body = {
                        "status": {"id": STATUS__MOVEMENT_BETWEEN_DEPARTMENTS},
                    }
                    planfix_post(f"task/{work_task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/reset_assembly_after_return_from_work")
async def reset_assembly_after_return_from_work(request: web.Request):
    try:
        body = await request.json()

        assembly_id = int(body["assembly_id"])
        sub_task_ids = body["sub_task_ids"]
        sub_task_template_ids = body["sub_task_template_ids"]
        work_belongs_to_assembly = body["work_belongs_to_assembly"]
        work_belongs_to_order = body["work_belongs_to_order"]
        subtask_counts = str(body["subtask_counts"]).split(",")

        logging.info("\nreset_assembly_after_return_from_work")
        logging.info("assembly_id %d", assembly_id)
        logging.info("sub_task_ids %s", sub_task_ids)
        logging.info("sub_task_template_ids %s", sub_task_template_ids)
        logging.info("work_belongs_to_assembly %s", work_belongs_to_assembly)
        logging.info("work_belongs_to_order %s", work_belongs_to_order)
        logging.info("subtask_counts %s", subtask_counts)

        _tmp = []
        _tmp2 = []
        for i in range(len(sub_task_ids)):
            _tmp.append("Нет")
            _tmp2.append(-1)
        task_tree = recreate_task_tree_from_list(assembly_id, 0, -1, sub_task_ids, sub_task_template_ids, subtask_counts, _tmp, work_belongs_to_assembly, work_belongs_to_order, _tmp2)
        task_tree.print_children()

        all_children = task_tree.get_all_children()
        for child_task in all_children:
            match child_task.template_id:
                case template_id if template_id == PLANFIX_TEMPLATE__ASSEMBLY:
                    body = {
                        "status": {"id": STATUS__CONSTRUCTORS},
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=true", body)
                case template_id if template_id == PLANFIX_TEMPLATE__DETAIL:
                    detail_work = planfix_get(f"task/{child_task.get_id()}?fields={FIELD__PROCESSING_TYPES}&sourceId=0").json()["task"]["customFieldData"][0]["value"]
                    body = {
                        "status": {"id": STATUS__CONSTRUCTORS},
                        "customFieldData": [
                            {
                                "field": {"id": FIELD__CURRENT_WORK_TYPE},
                                "value": {"id": detail_work[0]["id"]}
                            }
                        ]
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=true", body)
                case template_id if template_id == PLANFIX_TEMPLATE__PROCESSING:
                    if child_task.work_belongs_to_assembly:
                        body = {
                            "processId": PROCESS__CONSTRUCTORS,
                            "status": {"id": STATUS__CONSTRUCTORS},
                            "customFieldData": [
                                {
                                    "field": {"id": FIELD__DELETE_TASK},
                                    "value": False
                                }
                            ]
                        }
                        planfix_post(f"task/{child_task.get_id()}?silent=true", body)
                    elif child_task.work_belongs_to_order:
                        body = {
                            "processId": PROCESS__CONSTRUCTORS,
                            "status": {"id": STATUS__CONSTRUCTORS},
                            "customFieldData": [
                                {
                                    "field": {"id": FIELD__DELETE_TASK},
                                    "value": False
                                }
                            ]
                        }
                        planfix_post(f"task/{child_task.get_id()}?silent=true", body)

        # Sleeping and sending requests in that particular order is necessary because we need to trigger Planfix script that triggers on process change, not status change
        sleep(1)
        for child_task in all_children:
            match child_task.template_id:
                case template_id if template_id == PLANFIX_TEMPLATE__PROCESSING:
                    if child_task.work_belongs_to_assembly:
                        body = {
                            "customFieldData": [
                                {
                                    "field": {"id": FIELD__DELETE_TASK},
                                    "value": True
                                }
                            ]
                        }
                        planfix_post(f"task/{child_task.get_id()}?silent=true", body)
                    elif child_task.work_belongs_to_order:
                        body = {
                            "customFieldData": [
                                {
                                    "field": {"id": FIELD__DELETE_TASK},
                                    "value": True
                                }
                            ]
                        }
                        planfix_post(f"task/{child_task.get_id()}?silent=true", body)
                    else:
                        body = {
                            "processId": PROCESS__CONSTRUCTORS,
                            "customFieldData": [
                                {
                                    "field": {"id": FIELD__ACCEPT_WORK},
                                    "value": ""
                                }
                            ]
                        }
                        planfix_post(f"task/{child_task.get_id()}?silent=true", body)
                case _:
                    body = {
                        "processId": PROCESS__CONSTRUCTORS,
                    }
                    planfix_post(f"task/{child_task.get_id()}?silent=true", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
                    "status": {"id": STATUS__IN_WORK},
                    "customFieldData": [
                        {
                            "field": {"id": FIELD__ACCEPT_WORK},
                            "value": ""
                        }
                    ]
                }
                planfix_post(f"task/{int(work_task_id)}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/copy_child_status_to_parent")
async def copy_child_status_to_parent(request: web.Request):
    try:
        body = await request.json()

        parent_task_id_str = str(body["parent_task_id"])
        if parent_task_id_str == '':
            return PlanfixOk()

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

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

            planfix_post(f"task/{child_id}?silent=true", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
            if int(status_id) != STATUS__MATERIAL_EXISTENCE_CHECKING:
                all_complete = False
                break

            all_complete = True

        if all_complete is True:
            status = STATUS__IN_WORK if is_order_work_task else STATUS__MATERIAL_EXISTENCE_CHECKING
            body = {
                "status": {"id": status}
            }
            planfix_post(f"task/{work_task_id}?silent=false", body)

            if is_order_work_task:
                planfix_post(f"task/{order_task_id}?silent=false", body)

            logging.info("Complete: status %d", status)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
            if int(status_id) != STATUS__MATERIAL_EXISTENCE_CONFIRMATION:
                all_complete = False
                break

            all_complete = True

        if all_complete is True:
            body = {
                "status": {"id": STATUS__MATERIAL_EXISTENCE_CONFIRMATION}
            }
            planfix_post(f"task/{work_task_id}?silent=false", body)

            logging.info("Complete: status %d", STATUS__MATERIAL_EXISTENCE_CONFIRMATION)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
                    "status": {"id": STATUS__COMPLETE}
                }
                planfix_post(f"task/{int(detail_work_task_ids[i])}?silent=false", body)
                logging.info(planfix_get(f"task/{int(detail_work_task_ids[i])}?fields=name&sourceId=0").json()["task"]["name"])

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
        planfix_post(f"task/{task_id}?silent=true", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

            if status_id != STATUS__COMPLETE:
                all_subtasks_complete = False

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing parent task")

            if parent_task_first_level_assembly and order_assembly_work_count == 0:
                body = {
                    "status": {"id": STATUS__READY}
                }
            else:
                body = {
                    "status": {"id": STATUS__COMPLETE}
                }

            planfix_post(f"task/{task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

            if status_id != STATUS__COMPLETE:
                all_subtasks_complete = False

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing parent task")

            body = {
                "status": {"id": STATUS__COMPLETE}
            }
            planfix_post(f"task/{task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

            if status_id != STATUS__COMPLETE:
                all_subtasks_complete = False

        if all_subtasks_complete:
            logging.info("All subtasks tasks complete. Completing parent task")

            body = {
                "status": {"id": STATUS__READY if is_first_level_assembly else STATUS__COMPLETE}
            }
            planfix_post(f"task/{task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

        welding = confirmation_needed["welding"]
        for work in welding:
            if work == "Да":
                if USER_GROUP__WELDING_CONFIRMATION not in old_group_list:
                    body["assignees"]["groups"].append({"id": USER_GROUP__WELDING_CONFIRMATION})

                body["customFieldData"].append(
                    {
                        "field": {"id": FIELD__WELDING_CONFIRMATION},
                        "value": get_list_field_values(REST_API_TEMPLATE__ASSEMBLY, FIELD__WELDING_CONFIRMATION)[0]
                    }
                )
                update_task = True
                break

        turning_work = confirmation_needed["turning_work"][0].split(",") if len(confirmation_needed["turning_work"]) != 0 else []
        for work in turning_work:
            if work == "Да":
                if USER_GROUP__TURING_WORK_CONFIRMATION not in old_group_list:
                    body["assignees"]["groups"].append({"id": USER_GROUP__TURING_WORK_CONFIRMATION})

                body["customFieldData"].append(
                    {
                        "field": {"id": FIELD__TURING_WORK_CONFIRMATION},
                        "value": get_list_field_values(REST_API_TEMPLATE__ASSEMBLY, FIELD__TURING_WORK_CONFIRMATION)[0]
                    }
                )
                update_task = True
                break

        if update_task:
            logging.info("confirmation needed, adding confirmation people")
            planfix_post(f"task/{main_task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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

            if template_id == PLANFIX_TEMPLATE__DETAIL:
                if status_id == STATUS__MATERIAL_MOVEMENT:
                    all_materials_found = False

        if all_materials_found:
            logging.info("All materials found")

            body = {
                "status": {"id": STATUS__MATERIAL_EXISTENCE_CONFIRMATION},
                "customFieldData": [
                    {
                        "field": {"id": FIELD__MATERIAL_MOVEMENT},
                        "value": ""
                    }
                ]
            }
            planfix_post(f"task/{main_task_id}?silent=false", body)

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


@routes.post("/create_work_tasks_from_parent_task")
async def create_work_tasks_from_parent_task(request: web.Request):
    try:
        body = await request.json()

        order_id = int(body["order_id"])
        task_id = int(body["task_id"])
        work_to_order = body["work_to_order"]
        is_assembly = bool(body["is_assembly"])
        is_order = bool(body["is_order"])

        logging.info("\ncreate_work_tasks_from_parent_task")
        logging.info("task_id %d", task_id)
        logging.info("work_to_order %s", work_to_order)
        logging.info("is_assembly %s", "true" if is_assembly else "false")
        logging.info("is_order %s", "true" if is_order else "false")

        is_first = True
        for i in range(len(work_to_order[0])):
            if is_assembly and not is_order:
                body = {
                    "status": {"id": STATUS__IN_QUEUE},
                    "processId": PROCESS__PRODUCTION,
                    "customFieldData": [
                        {
                            "field": {"id": FIELD__CURRENT_WORK_TYPE_ASSEMBLY},
                            "value": {"id": int(work_to_order[0][i])}
                        },
                        {
                            "field": {"id": FIELD__WORK_FOR_ASSEMBLY},
                            "value": True
                        }
                    ]
                }
            elif not is_assembly and not is_order:
                body = {
                    "status": {"id": STATUS__CONSTRUCTORS},
                    "processId": PROCESS__CONSTRUCTORS,
                    "customFieldData": [
                        {
                            "field": {"id": FIELD__CURRENT_WORK_TYPE},
                            "value": {"id": int(work_to_order[0][i])}
                        }
                    ]
                }

                if is_first:
                    parent_body = {
                        "customFieldData": body["customFieldData"]
                    }
                    planfix_post(f"task/{task_id}?silent=true", parent_body)
            elif not is_assembly and is_order:
                body = {
                    "status": {"id": STATUS__IN_QUEUE},
                    "processId": PROCESS__PRODUCTION,
                    "customFieldData": [
                        {
                            "field": {"id": FIELD__CURRENT_WORK_TYPE_ASSEMBLY},
                            "value": {"id": int(work_to_order[0][i])}
                        },
                        {
                            "field": {"id": FIELD__WORK_FOR_ASSEMBLY},
                            "value": False
                        },
                        {
                            "field": {"id": FIELD__WORK_FOR_ORDER},
                            "value": True
                        }
                    ]
                }
            else:
                raise Exception(f"Unhandled work_creation from: is_assembly={is_assembly}, is_order={is_order}")

            body["name"] = work_to_order[1][i]
            body["template"] = {"id": REST_API_TEMPLATE__PROCESSING}
            body["parent"] = {"id": task_id}
            body["customFieldData"].append({
                "field": {"id": FIELD__ORDER},
                "value": order_id
            })
            planfix_post("task/", body)
            is_first = False

        return PlanfixOk()
    except Exception as e:
        print_error(e)
        return PlanfixError()


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
                        print_error(f"Unknown filed: {field["name"]}")

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
        return PlanfixError()


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
