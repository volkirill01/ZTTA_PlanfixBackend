from planfix_api import *
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from time import sleep

BOT_TOKEN = "7555357284:AAEpLJ7ayCI06YS1SbXb9ratAfZUV2QsmP8"

bot = telebot.TeleBot(BOT_TOKEN)

def get_tasks_in_work_or_ready_for_work():
    return planfix_post(f"/task/list", {"offset": 0, "pageSize": 100, "filterId": "1289394", "fields": "id,name,parent,template,status,105881", "sourceId": 0}).json()["tasks"]  # Filter 1289394 is "Заказы (В работе/Принять работу) (Для Task completion bot)" in ztta.planfix.com, fields 105881 Текущая Обработка

def get_task_by_id(task_id: int):
    return planfix_get(f"task/{task_id}?fields=id,status,template,name,parent,105596,105873&sourceId=0").json()["task"]

def get_order_by_machine(machine_task_id: int):
    order_task = get_task_by_id(get_task_by_id(machine_task_id)["customFieldData"][0]["value"]["id"])
    return { "id": order_task["id"], "name": order_task["name"], "order_number": order_task["customFieldData"][0]["value"] }

def get_machine_list():
    response = planfix_post(f"directory/14/entry/list", { "offset": 0, "pageSize": 100, "fields": "28", "groupsOnly": False }).json()["directoryEntries"]
    result = []
    for directory in response:
       if directory.__contains__("customFieldData"):
           result.append(directory["customFieldData"][0]["value"])

    return result

def create_keyboard():
    keyboard = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)

    button = KeyboardButton(text="Получить список заказов")
    keyboard.add(button)

    return keyboard

@bot.message_handler(commands=["start"])
def start(message):
    keyboard = create_keyboard()
    bot.send_message(message.chat.id, "Я работаю", reply_markup=keyboard)

def create_machines_list_button(chat_id):
    markup = InlineKeyboardMarkup()

    machine_list = get_machine_list()
    message_text = "Выберите станок:"

    for i, machine in enumerate(machine_list):
        markup.add(InlineKeyboardButton(machine, callback_data=f"getMachineTasks/{i}"))

    bot.send_message(chat_id, message_text, reply_markup=markup)

@bot.message_handler()
def get_user_text(message):
    if message.text == "Получить список заказов":
        create_machines_list_button(message.chat.id)

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    call_data = call.data.split('/')

    if call_data[0] == "getMachineTasks":
        markup = InlineKeyboardMarkup()

        machine_index = int(call_data[1])
        machine_list = get_machine_list()

        task_list = get_tasks_in_work_or_ready_for_work()

        orders_in_work = { }
        for i, task in enumerate(task_list):
            if task["customFieldData"][0]["value"]["value"] == machine_list[machine_index]:
                order = get_order_by_machine(task["id"])
                orders_in_work[order["id"]] = order

        for order in orders_in_work.values():
            markup.add(InlineKeyboardButton(f"{order['name']} ({order['order_number']})", callback_data=f"getOrderDetails/{order['id']}/{order['name']}/{machine_index}"))

        bot.send_message(call.from_user.id, f"Заказы на \"{machine_list[machine_index]}\":", reply_markup=markup)
    elif call_data[0] == "getOrderDetails":
        machine_index = int(call_data[3])
        machine_list = get_machine_list()
        markup = InlineKeyboardMarkup()

        order_id = int(call_data[1])
        order_task = get_task_by_id(order_id)
        tasks_in_work = get_tasks_in_work_or_ready_for_work()
        for i, task in enumerate(tasks_in_work):
            if get_order_by_machine(task["id"])["id"] == order_id:
                work_name = machine_list[machine_index]

                if task["customFieldData"][0]["value"]["value"] == work_name:
                    detail_task = None
                    if task["template"]["id"] == 14510: # Обработка
                        detail_task = get_task_by_id(task["parent"]["id"])
                    if task["template"]["id"] == 15685: # Раскрой листа
                        detail_task = task
                    is_task_in_work = task["status"]["id"] == 2 # В работе

                    cutting_pieces = planfix_get(f"task/{task["id"]}?fields=106024&sourceId=0").json()["task"]["customFieldData"][0]["value"]

                    task_name = detail_task["name"]
                    task_name = task_name.replace(work_name, "")
                    markup.add(InlineKeyboardButton(f'{"Р* " if is_task_in_work else ""}{task_name} | {cutting_pieces}', callback_data=f"getTaskStatusOptions/{task['id']}/{detail_task['id']}/{order_task['id']}"))

        bot.send_message(call.from_user.id, f"Раскрои по заказу \"{call_data[2]}\" ({order_task['customFieldData'][0]['value']}) {work_name}:", reply_markup=markup)

    elif call_data[0] == "getTaskStatusOptions":
        task = get_task_by_id(int(call_data[1]))
        detail_task = get_task_by_id(int(call_data[2]))
        order_task = get_task_by_id(int(call_data[3]))

        markup = InlineKeyboardMarkup()

        is_detail_ready_for_work = task["status"]["id"] == 228 # Принять работу
        if is_detail_ready_for_work:
            markup.add(InlineKeyboardButton(f'Принять работу', callback_data=f'changeTaskStatus/{task['id']}/{detail_task['id']}/{order_task['id']}/{2}')) # 2 - В работе

        is_detail_in_work = task["status"]["id"] == 2 # В работе
        if is_detail_in_work:
            markup.add(InlineKeyboardButton(f'Завершить работу', callback_data=f'changeTaskStatus/{task['id']}/{detail_task['id']}/{order_task['id']}/{3}')) # 2 - Завершённая

        bot.send_message(call.from_user.id, f"Заказ: {order_task['name']} ({order_task['customFieldData'][0]['value']})\nРаскрой: \"{detail_task['name']}\"", reply_markup=markup)

    elif call_data[0] == "changeTaskStatus":
        task_id = int(call_data[1])
        detail_task = get_task_by_id(int(call_data[2]))
        order_task = get_task_by_id(int(call_data[3]))
        status_id = int(call_data[4])
        status_name = "В работе" if status_id == 2 else "Завершённая" if status_id == 3 else f"<unknown status id {status_id}>"
        bot.send_message(call.from_user.id, f"Заказ: {order_task['name']} ({order_task['customFieldData'][0]['value']})\nРаскрой: \"{detail_task['name']}\"\nТеперь \"{status_name}\"")

        planfix_post(f"task/{task_id}?silent=false", {
            "status": {
                "id": status_id
            },
            "customFieldData": [
                {
                    "field": {
                        "id": 105877 # Завершивший работу
                    },
                    "value": f"{call.from_user.last_name[0] + '. ' if call.from_user.last_name is not None else ''}{call.from_user.first_name}"
                }
            ]
        })

# RUN
def main():
    print("\033[32m====================================================\n"
          "\033[35m(ZTTA_Planfix_TaskCompletion_Bot)\033[32m  ---Bot start---\n"
          f"====================================================\033[0m")

    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as _ex:
            print(f"\033[31mError: {_ex}\033[0m")
            sleep(15)


if __name__ == "__main__":
    main()
