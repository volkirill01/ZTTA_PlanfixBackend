import pathlib

from structs import *
from dxf_generator import DXFGenerator


debug_mode = True

input_author: str = "В.Кирилл"
if not debug_mode:
    input_author = input("Автор детали: ")

input_number: str = "011220"
if not debug_mode:
    input_number = input("Номер заказа: ")

input_part_name: str = "test_file"
if not debug_mode:
    input_part_name = input("Название детали: ")

input_part_thickness: float = 2.0
if not debug_mode:
    input_part_thickness = float(input("Толщина: "))

input_part_count: int = 3
if not debug_mode:
    input_part_count = int(input("Количество: "))

input_part_type: int = DXFGenerator.PartType.CircleWithHole
if not debug_mode:
    input_part_type = int(input(f"Тип детали:\n"
                                f"\t{DXFGenerator.PartType.Rect} - Прямоугольник\n"
                                f"\t{DXFGenerator.PartType.Triangle} - Косынка\n"
                                f"\t{DXFGenerator.PartType.Circle} - Круг\n"
                                f"\t{DXFGenerator.PartType.CircleWithHole} - Шайба\n"))

output_directory = r"E:\_Files\Projects\Python\Planfix\out" # r"\\storage\UserSpace\IT\Kirill"

if input_part_type == DXFGenerator.PartType.Rect:
    input_rect_width = 100
    if not debug_mode:
        input_rect_width = float(input("Ширина: "))

    input_rect_height = 200
    if not debug_mode:
        input_rect_height = float(input("Высота: "))

    generator = DXFGenerator(output_directory)
    generator.reset(input_part_thickness, input_part_count, input_part_name, input_part_name, input_author, input_number, "Г2С", "Лазер/Хахтарин")
    generator.generate_rect(Vec2(0, 0), Vec2(input_rect_width, input_rect_height))
    generator.save()

elif input_part_type == DXFGenerator.PartType.Triangle:
    input_triangle_width = 100
    if not debug_mode:
        input_triangle_width = float(input("Ширина: "))

    input_triangle_height = 200
    if not debug_mode:
        input_triangle_height = float(input("Высота: "))

    generator = DXFGenerator(output_directory)
    generator.reset(input_part_thickness, input_part_count, input_part_name, input_part_name, input_author, input_number, "Г2С", "Лазер/Хахтарин")
    generator.generate_triangle(Vec2(0, 0), Vec2(input_triangle_width, input_triangle_height))
    generator.save()

elif input_part_type == DXFGenerator.PartType.Circle:
    input_radius = 300
    if not debug_mode:
        input_radius = float(input("Радиус: "))

    generator = DXFGenerator(output_directory)
    generator.reset(input_part_thickness, input_part_count, input_part_name, input_part_name, input_author, input_number, "Г2С", "Лазер/Хахтарин")
    generator.generate_circle(Vec2(input_radius, input_radius), input_radius)
    generator.save()

elif input_part_type == DXFGenerator.PartType.CircleWithHole:
    input_radius = 300
    if not debug_mode:
        input_radius = float(input("Радиус: "))

    input_hole_radius = 150
    if not debug_mode:
        input_hole_radius = float(input("Радиус отверстия: "))

    generator = DXFGenerator(output_directory)
    generator.reset(input_part_thickness, input_part_count, input_part_name, input_part_name, input_author, input_number, "Г2С", "Лазер/Хахтарин")
    generator.generate_circle_with_hole(Vec2(input_radius, input_radius), input_radius, input_hole_radius)
    generator.save()
