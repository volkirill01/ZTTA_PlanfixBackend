import inspect
import traceback
import logging


class ConsoleColor:
    Clear = "\033[0m"
    Red = "\033[31m"
    Green = "\033[32m"
    Yellow = "\033[93m"
    Gray = "\033[37m"


def get_current_function_name():
    return inspect.stack()[2][3]


def get_current_code_point():
    line = int(str(inspect.stack()[2][0]).split(",")[2].lstrip().replace("line ", ""))
    return line


def print_error(e: str | Exception = None):
    message = f"[{get_current_function_name()}:{get_current_code_point()}] Error occurred: {traceback.format_exc()}"

    with open("app.log", "a") as file:
        file.write(message.replace("", ""))
        file.write("\n")

    logging.error(f"{ConsoleColor.Red}{message}{ConsoleColor.Clear}")


def print_warn(e: str = None):
    message = f"[{get_current_function_name()}:{get_current_code_point()}] Warning occurred: {traceback.format_exc()}"

    with open("app.log", "a") as file:
        file.write(message.replace("", ""))
        file.write("\n")

    logging.error(f"{ConsoleColor.Yellow}{message}{ConsoleColor.Clear}")
