# This code for adding line numbers at the end of each line for P table of IGS
# example_igs = """"""
#
# out = ""
# last_number = 0
# for i, line in enumerate(example_igs.split("\n")):
#     print(i)
#     found = False
#     if len(line) != 0:
#
#         if line[len(line)-1] == ' ':
#             last_number = last_number + 1
#             found = True
#             out += line + str(last_number) + "\n"
#         elif found:
#             last_number = last_number + 1
#             #last_number = int(line[len(line)-4:len(line)].lstrip())
#             out += line[len(line)-4:len(line)] + str(last_number) + "\n"
#         else:
#             out += line + "\n"
#
# print(out)
# exit(-1)

TEMPLATE_PATH__CIRCLE = "igs_generator/templates/circle.igs"
TEMPLATE_PATH__RECT = "igs_generator/templates/rect.igs"

LENGTH_TOKEN = "$length$"

OUTER_RADIUS_TOKEN = "$outer_radius$"
INNER_RADIUS_TOKEN = "$inner_radius$"

OUTER_WIDTH_TOKEN = "$outer_width$"
MIDDLE_WIDTH_TOKEN = "$middle_width$"
INNER_WIDTH_TOKEN = "$inner_width$"

OUTER_HEIGHT_TOKEN = "$outer_height$"
MIDDLE_HEIGHT_TOKEN = "$middle_height$"
INNER_HEIGHT_TOKEN = "$inner_height$"


def replace_token_with_value(text: str, token: str, value):
    token_pos = text.find(token)
    token_length = len(token)

    if token_pos != -1:
        return text[:token_pos] + str(value) + text[token_pos + token_length:token_pos + token_length + 3] + (" " * (token_length - len(str(value)))) + text[token_pos + token_length + 3:]

    return text

class IGSGenerator:
    class TubeType:
        Circle = 0
        Rectangle = 1

    def __init__(self, output_directory: str):
        self.output_directory = output_directory
        self.filepath = ""
        self.igs_data = ""

    def reset(self, filepath: str):
        self.filepath = filepath
        self.igs_data = ""

    def generate_circle_tube(self, outer_diameter: float, thickness: float, length: float):
        outer_radius = outer_diameter / 2
        inner_radius = outer_radius - thickness

        with open(TEMPLATE_PATH__CIRCLE, "r", encoding="utf8") as f:
            template_igs = f.read()

        self.igs_data = ""
        for line in template_igs.split("\n"):
            line = replace_token_with_value(line, LENGTH_TOKEN, length)
            line = replace_token_with_value(line, OUTER_RADIUS_TOKEN, outer_radius)
            line = replace_token_with_value(line, INNER_RADIUS_TOKEN, inner_radius)

            self.igs_data += line + "\n"

        self.filepath = f"Tube_C_{outer_diameter}x{thickness}_{length}mm".replace(",", ".")

    def generate_rect_tube(self, width: float, height: float, thickness: float, length: float):
        outer_width = width / 2
        middle_width = outer_width - thickness
        inner_width = outer_width - (thickness * 2)

        outer_height = height / 2
        middle_height = outer_height - thickness
        inner_height = outer_height - (thickness * 2)

        with open(TEMPLATE_PATH__RECT, "r", encoding="utf8") as f:
            template_igs = f.read()

        self.igs_data = ""
        for line in template_igs.split("\n"):
            line = replace_token_with_value(line, LENGTH_TOKEN, length)

            line = replace_token_with_value(line, OUTER_WIDTH_TOKEN, outer_width)
            line = replace_token_with_value(line, MIDDLE_WIDTH_TOKEN, middle_width)
            line = replace_token_with_value(line, INNER_WIDTH_TOKEN, inner_width)

            line = replace_token_with_value(line, OUTER_HEIGHT_TOKEN, outer_height)
            line = replace_token_with_value(line, MIDDLE_HEIGHT_TOKEN, middle_height)
            line = replace_token_with_value(line, INNER_HEIGHT_TOKEN, inner_height)

            self.igs_data += line + "\n"

        self.filepath = f"Tube_R_{width}x{height}x{thickness}_{length}mm".replace(",", ".")

    def save(self) -> str:
        # Save IGS to output filepath
        igs_filepath = self.output_directory + '\\' + self.filepath + ".igs"

        with open(igs_filepath, "w", encoding="utf8") as f:
            f.write(self.igs_data)

        return igs_filepath
