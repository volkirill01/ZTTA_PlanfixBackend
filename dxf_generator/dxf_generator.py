import logging
import time
import ezdxf
from ezdxf.addons.drawing import matplotlib

from structs import *

class DXFGenerator:
    class PartType:
        Rect = 0
        RectWithHole = 1
        Triangle = 2
        Circle = 3
        CircleWithHole = 4
        Text = 5

    def __init__(self, output_directory: str):
        self.part_name = ""
        self.filepath = ""
        self.dimensions = Rect()

        self.output_directory = output_directory
        self.author = ""
        self.number = ""

        self.material = ""
        self.part_thickness = 0
        self.part_count = 1

        self.technical_path = ""

        self.doc = ezdxf.new('R2010')  # Create a new DXF drawing in R2010 format
        self.msp = self.doc.modelspace()

        self.pieces = []

    def reset(self, part_thickness: float, part_count: int, part_name: str, filepath: str, author: str, number: str, material: str, technical_path: str):
        self.part_name = part_name
        self.filepath = filepath
        self.author = author
        self.number = number

        self.material = material
        self.part_thickness = part_thickness
        self.part_count = part_count

        self.technical_path = technical_path

        self.dimensions.reset()

        self.doc = ezdxf.new('R2010')  # Create a new DXF drawing in R2010 format
        self.msp = self.doc.modelspace()

        self.pieces.clear()

    def generate_rect(self, position: Vec2, size: Vec2):
        self.msp.add_polyline2d([
            (position.x, position.y),
            (position.x + size.x, position.y),
            (position.x + size.x, position.y + size.y),
            (position.x, position.y + size.y)],
            close=True)
        self.pieces.append({ "type": self.PartType.Rect, "position": position, "size": size })

        self.dimensions.start.x = min(self.dimensions.start.x, position.x)
        self.dimensions.start.y = min(self.dimensions.start.y, position.y)
        self.dimensions.end.x = max(self.dimensions.end.x, position.x + size.x)
        self.dimensions.end.y = max(self.dimensions.end.y, position.y + size.y)

    def generate_rect_with_hole(self, position: Vec2, size: Vec2, hole_size: Vec2):
        self.msp.add_polyline2d([
            (position.x, position.y),
            (position.x + size.x, position.y),
            (position.x + size.x, position.y + size.y),
            (position.x, position.y + size.y)],
            close=True)
        self.msp.add_polyline2d([
            (position.x + (size.x - hole_size.x) / 2, position.y + (size.y - hole_size.y) / 2),
            (position.x + (size.x - hole_size.x) / 2 + hole_size.x, position.y + (size.y - hole_size.y) / 2),
            (position.x + (size.x - hole_size.x) / 2 + hole_size.x, position.y + (size.y - hole_size.y) / 2 + hole_size.y),
            (position.x + (size.x - hole_size.x) / 2, position.y + (size.y - hole_size.y) / 2 + hole_size.y)],
            close=True)
        self.pieces.append({ "type": self.PartType.RectWithHole, "position": position, "size": size, "hole_size": hole_size })

        self.dimensions.start.x = min(self.dimensions.start.x, position.x)
        self.dimensions.start.y = min(self.dimensions.start.y, position.y)
        self.dimensions.end.x = max(self.dimensions.end.x, position.x + size.x)
        self.dimensions.end.y = max(self.dimensions.end.y, position.y + size.y)

    def generate_triangle(self, position: Vec2, size: Vec2):
        self.msp.add_polyline2d([
            (position.x, position.y + size.y),
            (position.x, position.y),
            (position.x + size.x, position.y)],
            close=True)
        self.pieces.append({ "type": self.PartType.Triangle, "position": position, "size": size })

        self.dimensions.start.x = min(self.dimensions.start.x, position.x)
        self.dimensions.start.y = min(self.dimensions.start.y, position.y)
        self.dimensions.end.x = max(self.dimensions.end.x, position.x + size.x)
        self.dimensions.end.y = max(self.dimensions.end.y, position.y + size.y)

    def generate_circle(self, position: Vec2, diameter: float):
        self.msp.add_circle((position.x, position.y), radius=diameter / 2)
        self.pieces.append({ "type": self.PartType.Circle, "position": position, "diameter": diameter })

        self.dimensions.start.x = min(self.dimensions.start.x, position.x - diameter / 2)
        self.dimensions.start.y = min(self.dimensions.start.y, position.y - diameter / 2)
        self.dimensions.end.x = max(self.dimensions.end.x, position.x + diameter / 2)
        self.dimensions.end.y = max(self.dimensions.end.y, position.y + diameter / 2)

    def generate_circle_with_hole(self, position: Vec2, diameter: float, hole_diameter: float):
        self.msp.add_circle((position.x, position.y), radius=diameter / 2)
        self.msp.add_circle((position.x, position.y), radius=hole_diameter / 2)
        self.pieces.append({ "type": self.PartType.CircleWithHole, "position": position, "diameter": diameter, "hole_diameter": hole_diameter })

        self.dimensions.start.x = min(self.dimensions.start.x, position.x - diameter / 2)
        self.dimensions.start.y = min(self.dimensions.start.y, position.y - diameter / 2)
        self.dimensions.end.x = max(self.dimensions.end.x, position.x + diameter / 2)
        self.dimensions.end.y = max(self.dimensions.end.y, position.y + diameter / 2)

    def generate_text(self, position: Vec2, text: str):
        self.pieces.append({ "type": self.PartType.Text, "text": text, "position": position })

    def add_blueprint_block(self, pos: Vec2, width: float, height: float, text: str):
        self.msp.add_polyline2d([
            (pos.x, pos.y),
            (pos.x + width, pos.y),
            (pos.x + width, pos.y + height),
            (pos.x, pos.y + height)],
            close=True)

        text_height = height/3
        text_entity = self.msp.add_text(text, height=text_height)
        text_entity.set_placement((pos.x + text_height, pos.y + text_height))


    def save(self) -> [str, str]:
        # Save DXF to output filepath
        dxf_filepath = self.output_directory + '\\' + self.filepath + ".dxf"
        self.doc.saveas(dxf_filepath)
        logging.info(f"DXF file successfully saved to: \"{dxf_filepath}\"")

        #region Size, margin, position calculations
        paper_size = Vec2(297, 210)

        # Flip orientation if needed
        if self.dimensions.size().x < self.dimensions.size().y:
            old_x = paper_size.x
            paper_size.x = paper_size.y
            paper_size.y = old_x

        def expand_bounding_box_with_aspect_ratio(bb_min: Vec2, bb_max: Vec2, margin: float, target_aspect: Vec2) -> tuple[Vec2, Vec2]:
            # Add margin to the bounding box
            expanded_min = bb_min - Vec2(margin, margin)
            expanded_max = bb_max + Vec2(margin, margin)

            # Compute the expanded bounding box size
            size = expanded_max - expanded_min
            aspect_ratio = target_aspect.x / target_aspect.y

            # Calculate the current aspect ratio
            current_aspect = size.x / size.y

            # Adjust to match target aspect ratio
            if current_aspect > aspect_ratio:
                # Expand height to match the aspect ratio
                new_height = size.x / aspect_ratio
                height_diff = (new_height - size.y) / 2
                expanded_min.y -= height_diff
                expanded_max.y += height_diff
            else:
                # Expand width to match the aspect ratio
                new_width = size.y * aspect_ratio
                width_diff = (new_width - size.x) / 2
                expanded_min.x -= width_diff
                expanded_max.x += width_diff

            return expanded_min, expanded_max

        bb_min, bb_max = expand_bounding_box_with_aspect_ratio(
            self.dimensions.start,
            self.dimensions.end,
            max(self.dimensions.size().x, self.dimensions.size().y) * 0.1,
            paper_size)
        blueprint_size = bb_max - bb_min
        blueprint_pos = bb_min
        scaling_factor = max(blueprint_size.x, blueprint_size.y) * 2

        margin = scaling_factor * 0.17
        blueprint_size += Vec2(margin * 2, margin * 2)
        blueprint_pos -= Vec2(margin, margin)

        dim_offset = scaling_factor * 0.025
        dim_text_size = scaling_factor * 0.008 # 0.015
        #endregion

        if "DASHDOT_CUSTOM" not in self.doc.linetypes:
            self.doc.linetypes.new("DASHDOT_CUSTOM", dxfattribs=
            {
                "description": "Dash-dot - . - . -",
                "pattern": [0.5, -0.5,  # Dash (0.5), Space (-0.5)
                            8.0 * (dim_text_size / 10),  # Dot (8.0)
                            -2.5 * (dim_text_size / 10)],  # Space (-2.5)
            })

        #region Parts
        def style_dim(dim, text_size: float):
            dim.dimstyle.dxf.dimtxt = text_size
            dim.set_arrows(size=text_size)
            dim.render()

        for part in self.pieces:
            part_pos = part["position"]

            match part["type"]:
                case self.PartType.Rect:
                    rect_size = part["size"]
                    # Width
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x, part_pos.y + rect_size.y + dim_offset),
                        p1=(part_pos.x, part_pos.y + rect_size.y),
                        p2=(part_pos.x + rect_size.x, part_pos.y + rect_size.y),
                        angle=0,
                        text=f"{rect_size.x}mm"), dim_text_size)
                    # Height
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x - dim_offset, part_pos.y),
                        p1=(part_pos.x, part_pos.y),
                        p2=(part_pos.x, part_pos.y + rect_size.y),
                        angle=90,
                        text=f"{rect_size.y}mm"), dim_text_size)

                case self.PartType.RectWithHole:
                    rect_size = part["size"]
                    rect_hole_size = part["hole_size"]

                    self.msp.add_line((part_pos.x + rect_size.x / 2 - rect_hole_size.x / 2 - dim_offset, part_pos.y + rect_size.y / 2), (part_pos.x + rect_size.x / 2 + rect_hole_size.x / 2 + dim_offset, part_pos.y + rect_size.y / 2), dxfattribs={"linetype": "DASHDOT_CUSTOM"})
                    self.msp.add_line((part_pos.x + rect_size.x / 2, part_pos.y + rect_size.y / 2 - rect_hole_size.y / 2 - dim_offset), (part_pos.x + rect_size.x / 2, part_pos.y + rect_size.y / 2 + rect_hole_size.y / 2 + dim_offset), dxfattribs={"linetype": "DASHDOT_CUSTOM"})

                    # Width
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x, part_pos.y + rect_size.y + dim_offset),
                        p1=(part_pos.x, part_pos.y + rect_size.y),
                        p2=(part_pos.x + rect_size.x, part_pos.y + rect_size.y),
                        angle=0,
                        text=f"{rect_size.x}mm"), dim_text_size)
                    # Height
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x - dim_offset, part_pos.y),
                        p1=(part_pos.x, part_pos.y),
                        p2=(part_pos.x, part_pos.y + rect_size.y),
                        angle=90,
                        text=f"{rect_size.y}mm"), dim_text_size)

                    # Hole width
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x + (rect_size.x - rect_hole_size.x) / 2, part_pos.y + (rect_size.y - rect_hole_size.y) / 2 - dim_offset * 2),
                        p1=(part_pos.x + (rect_size.x - rect_hole_size.x) / 2, part_pos.y + (rect_size.y - rect_hole_size.y) / 2),
                        p2=(part_pos.x + (rect_size.x - rect_hole_size.x) / 2 + rect_hole_size.x, part_pos.y + (rect_size.y - rect_hole_size.y) / 2),
                        angle=0,
                        text=f"{rect_hole_size.x}mm"), dim_text_size)
                    # Hole height
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x + rect_size.x - (rect_size.x - rect_hole_size.x) / 2 + dim_offset * 2, part_pos.y + (rect_size.y - rect_hole_size.y) / 2),
                        p1=(part_pos.x + rect_size.x - (rect_size.x - rect_hole_size.x) / 2, part_pos.y + (rect_size.y - rect_hole_size.y) / 2),
                        p2=(part_pos.x + rect_size.x - (rect_size.x - rect_hole_size.x) / 2, part_pos.y + (rect_size.y - rect_hole_size.y) / 2 + rect_hole_size.y),
                        angle=90,
                        text=f"{rect_hole_size.y}mm"), dim_text_size)

                case self.PartType.Triangle:
                    triangle_size = part["size"]
                    # Width
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x, part_pos.y - dim_offset),
                        p1=(part_pos.x, part_pos.y),
                        p2=(part_pos.x + triangle_size.x, part_pos.y),
                        angle=0,
                        text=f"{triangle_size.x}mm"), dim_text_size)
                    # Height
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x - dim_offset, part_pos.y),
                        p1=(part_pos.x, part_pos.y),
                        p2=(part_pos.x, part_pos.y + triangle_size.y),
                        angle=90,
                        text=f"{triangle_size.y}mm"), dim_text_size)

                case self.PartType.Circle:
                    circle_diameter = part["diameter"]
                    # Diameter
                    style_dim(self.msp.add_diameter_dim(
                        (part_pos.x, part_pos.y),
                        angle=180,
                        radius=circle_diameter / 2,
                        text=f"{circle_diameter}mm"),
                        dim_text_size)

                case self.PartType.CircleWithHole:
                    circle_diameter = part["diameter"]
                    circle_hole_diameter = part["hole_diameter"]

                    self.msp.add_line((part_pos.x - circle_diameter / 2 - dim_offset, part_pos.y), (part_pos.x + circle_diameter / 2 + dim_offset, part_pos.y), dxfattribs={"linetype": "DASHDOT_CUSTOM"})
                    self.msp.add_line((part_pos.x, part_pos.y - circle_diameter / 2 - dim_offset), (part_pos.x, part_pos.y + circle_diameter / 2 + dim_offset), dxfattribs={"linetype": "DASHDOT_CUSTOM"})

                    # Diameter
                    style_dim(self.msp.add_linear_dim(
                        base=(part_pos.x - circle_diameter / 2, part_pos.y - circle_diameter / 2 - dim_offset),
                        p1=(part_pos.x - circle_diameter / 2, part_pos.y),
                        p2=(part_pos.x + circle_diameter / 2, part_pos.y),
                        angle=0,
                        text=f"{circle_diameter}mm"), dim_text_size)
                    # Hole diameter
                    style_dim(self.msp.add_diameter_dim(
                        (part_pos.x, part_pos.y),
                        angle=-225,
                        radius=circle_hole_diameter / 2,
                        text=f"{circle_hole_diameter}mm"),
                        dim_text_size)

                case self.PartType.Text:
                    text = part["text"]

                    text_entity = self.msp.add_text(text=text, height=dim_text_size)
                    text_entity.set_placement((part_pos.x, part_pos.y))
        #endregion

        #region Blocks
        block_width = scaling_factor * 0.32
        block_height = scaling_factor * 0.020
        block_offset = 0.0

        block_pos = Vec2(blueprint_pos.x + blueprint_size.x - block_width, blueprint_pos.y + block_offset)
        self.add_blueprint_block(block_pos, block_width, block_height, f"Технологический маршрут: {self.technical_path}")
        block_offset += block_height

        block_pos = Vec2(blueprint_pos.x + blueprint_size.x - block_width, blueprint_pos.y + block_offset)
        self.add_blueprint_block(block_pos, block_width, block_height, f"Автор: {self.author}")
        block_offset += block_height

        block_pos = Vec2(blueprint_pos.x + blueprint_size.x - block_width, blueprint_pos.y + block_offset)
        self.add_blueprint_block(block_pos, block_width, block_height, f"Толщина: {self.part_thickness}mm")
        block_offset += block_height

        block_pos = Vec2(blueprint_pos.x + blueprint_size.x - block_width, blueprint_pos.y + block_offset)
        self.add_blueprint_block(block_pos, block_width, block_height, f"Материал: {self.material}")
        block_offset += block_height

        block_pos = Vec2(blueprint_pos.x + blueprint_size.x - block_width, blueprint_pos.y + block_offset)
        self.add_blueprint_block(block_pos, block_width, block_height, f"Количество: {self.part_count}")
        block_offset += block_height

        block_pos = Vec2(blueprint_pos.x + blueprint_size.x - block_width, blueprint_pos.y + block_offset)
        self.add_blueprint_block(block_pos, block_width, block_height, f"Номер заказа: {self.number}")
        block_offset += block_height
        #endregion

        #region Labels
        name_height = dim_text_size * 1.3
        name_entity = self.msp.add_text(self.part_name, height=name_height)
        name_margin = Vec2(scaling_factor * 0.01, scaling_factor * 0.05)
        name_entity.set_placement((
            blueprint_pos.x + blueprint_size.x - len(self.part_name) * name_height - name_margin.x,
            blueprint_pos.y + blueprint_size.y - name_height - name_margin.y))

        date_height = dim_text_size * 0.8
        date_str = str(time.strftime("%d.%m.%Yг %H:%M:%S", time.localtime()))
        date_entity = self.msp.add_text(date_str, height=date_height, rotation=-90)
        date_margin = Vec2(scaling_factor * 0.025 / 2, scaling_factor * 0.05 / 4)
        date_entity.set_placement((
            blueprint_pos.x + blueprint_size.x - date_height + date_margin.x,
            blueprint_pos.y + blueprint_size.y - date_margin.y))
        #endregion

        # Frame around all parts
        self.msp.add_polyline2d(
        [
            (blueprint_pos.x, blueprint_pos.y),
            (blueprint_pos.x + blueprint_size.x, blueprint_pos.y),
            (blueprint_pos.x + blueprint_size.x, blueprint_pos.y + blueprint_size.y),
            (blueprint_pos.x, blueprint_pos.y + blueprint_size.y)
        ], close=True)

        # Create the PDF
        pdf_filepath = dxf_filepath.replace(".dxf", ".pdf")
        mm_to_inch = 25.4
        matplotlib.qsave(self.msp, pdf_filepath, bg="#FFFFFF", size_inches=(paper_size.x / mm_to_inch, paper_size.y / mm_to_inch), dpi=300)
        logging.info(f"PDF file successfully saved to: \"{pdf_filepath}\"")

        return [dxf_filepath, pdf_filepath]
