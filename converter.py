# import math
# import os
# import shutil
# import time
# import psutil
# import ezdxf
# from ezdxf.addons.drawing import matplotlib
# from pyautocad import Autocad, APoint
# import subprocess
# from base import *
#
# TEXT_SCALE_FACTOR = 20
# TEXT_OFFSET = 230
#
# dwg_dir = os.path.abspath("resources")
# dxf_dir = os.path.abspath("resources/tmp")
#
# max_text_size = 1
# dimension_width = None
# dimension_height = None
#
#
# def calculate_extents(_model_space):
#     min_x = float('inf')
#     min_y = float('inf')
#     max_x = float('-inf')
#     max_y = float('-inf')
#
#     for obj in _model_space:
#         try:
#             if obj.ObjectName == "AcDbCircle":  # Handle circles explicitly
#                 center = obj.Center
#                 radius = obj.Radius
#                 min_x = min(min_x, center[0] - radius)
#                 min_y = min(min_y, center[1] - radius)
#                 max_x = max(max_x, center[0] + radius)
#                 max_y = max(max_y, center[1] + radius)
#             elif obj.ObjectName == "AcDbPolyline":  # Handle polylines manually
#                 coordinates = obj.Coordinates  # Get the vertices of the polyline
#                 for i in range(0, len(coordinates), 2):  # Iterate through the x, y pairs
#                     x, y = coordinates[i], coordinates[i + 1]
#                     min_x = min(min_x, x)
#                     min_y = min(min_y, y)
#                     max_x = max(max_x, x)
#                     max_y = max(max_y, y)
#             elif obj.ObjectName == "AcDbArc":  # Handle arcs explicitly
#                 center = obj.Center
#                 radius = obj.Radius
#                 start_angle = obj.StartAngle  # Angle in radians
#                 end_angle = obj.EndAngle  # Angle in radians
#
#                 # Calculate key points on the arc
#                 points = [
#                     (center[0] + radius * math.cos(start_angle), center[1] + radius * math.sin(start_angle)),
#                     (center[0] + radius * math.cos(end_angle), center[1] + radius * math.sin(end_angle)),
#                     (center[0] + radius, center[1]),  # Rightmost point (0 radians)
#                     (center[0] - radius, center[1]),  # Leftmost point (pi radians)
#                     (center[0], center[1] + radius),  # Top point (pi/2 radians)
#                     (center[0], center[1] - radius)  # Bottom point (3pi/2 radians)
#                 ]
#
#                 # Update min/max extents based on arc points
#                 for x, y in points:
#                     min_x = min(min_x, x)
#                     min_y = min(min_y, y)
#                     max_x = max(max_x, x)
#                     max_y = max(max_y, y)
#             elif obj.ObjectName == "AcDbLine":  # Handle lines explicitly
#                 start_point = obj.StartPoint
#                 end_point = obj.EndPoint
#                 min_x = min(min_x, start_point[0], end_point[0])
#                 min_y = min(min_y, start_point[1], end_point[1])
#                 max_x = max(max_x, start_point[0], end_point[0])
#                 max_y = max(max_y, start_point[1], end_point[1])
#             elif hasattr(obj, 'GetBoundingBox'):  # Handle other objects with GetBoundingBox
#                 ext_min, ext_max = obj.GetBoundingBox()
#                 min_x = min(min_x, ext_min.x)
#                 min_y = min(min_y, ext_min.y)
#                 max_x = max(max_x, ext_max.x)
#                 max_y = max(max_y, ext_max.y)
#             else:
#                 print_error(f"Object of type '{obj.ObjectName}' does not support GetBoundingBox or vertex extraction.")
#         except Exception as e:
#             print_error(f"Failed to get bounding box for object of type '{obj.ObjectName}': {e}")
#
#     if min_x == float('inf') or min_y == float('inf'):
#         print_error("No valid bounding box found.")
#         return None, None
#
#     return APoint(min_x, min_y), APoint(max_x, max_y)
#
#
# def get_unit_name(_doc):
#     # Get the unit name from the INSUNITS system variable
#     unit_map = {
#         0: "Unitless",
#         1: "in",  # Inches
#         2: "ft",  # Feet
#         3: "mi",  # Miles
#         4: "mm",  # Millimeters
#         5: "cm",  # Centimeters
#         6: "m",  # Meters
#         7: "km",  # Kilometers
#         8: "µin",  # Microinches
#         9: "mil",  # Mils
#         10: "yd",  # Yards
#         11: "Å",  # Angstroms
#         12: "nm",  # Nanometers
#         13: "µm",  # Microns
#         14: "dm",  # Decimeters
#         15: "dam",  # Dekameters
#         16: "hm",  # Hectometers
#         17: "Gm",  # Gigameters
#         18: "AU",  # Astronomical Units
#         19: "ly",  # Light Years
#         20: "pc"  # Parsecs
#     }
#
#     try:
#         unit_type = _doc.GetVariable("INSUNITS")  # Get the units from the system variable
#         return unit_map.get(unit_type, "Units")
#     except Exception as e:
#         print_error(f"Failed to retrieve units: {e}")
#         return "Units"
#
#
# def check_file_exists(_filepath):
#     if not os.path.exists(_filepath):
#         raise FileNotFoundError(f"File not found: {_filepath}")
#
#
# # Step 1: Convert DWG to DXF using ODA File Converter
# def dwg_to_dxf(_dwg_filepath, _dxf_filepath):
#     # Ensure the DWG file exists
#     check_file_exists(_dwg_filepath)
#
#     oda_converter_path = r"C:\Program Files\ODA\ODAFileConverter 25.8.0\ODAFileConverter.exe"
#     command = f"{oda_converter_path} \"{_dwg_filepath}\" \"{_dxf_filepath}\" ACAD2013 DXF 0 0"
#     try:
#         subprocess.run(command, check=True)
#     except subprocess.CalledProcessError as e:
#         print_error(f"Command failed with exit code {e.returncode}")
#         print_error(e.output)  # This will show the output if there's an error
#
#
# def dxf_to_pdf(_filepath):
#     dxf_file = _filepath
#     pdf_file = _filepath.replace(".dxf", ".pdf")
#
#     # Ensure the DXF file exists
#     check_file_exists(dxf_file)
#     # Load the DXF file
#     pdf_doc = ezdxf.readfile(dxf_file)
#     # Set up a drawing
#     msp = pdf_doc.modelspace()
#     # Create the PDF
#     matplotlib.qsave(msp, pdf_file)
#
#     return pdf_file
#
#
# acad = None
#
#
# def wait_for_autocad_ready():
#     global acad
#
#     while True:
#         try:
#             # Attempt to perform a simple operation to check if AutoCAD is ready
#             print(acad.ActiveDocument.Name)  # Accessing a property to check if it's responsive
#             break  # If successful, exit the loop
#         except Exception as e:
#             print_warn(e)
#             time.sleep(2.0)  # Wait briefly before trying again
#
#
# def add_dimensions_to_drawing(_filepath):
#     global acad, max_text_size, dimension_width, dimension_height
#
#     print(_filepath)
#     if not os.path.exists(_filepath):
#         print_error(f"DWG file not found at {_filepath}")
#         return
#
#     try:
#         time.sleep(1)
#         acad.Application.Documents.Open(_filepath)
#         wait_for_autocad_ready()  # Wait for AutoCAD to be ready
#
#         active_doc = acad.Application.ActiveDocument
#         if not active_doc:
#             print_error("Failed to set the active document.")
#             return
#         wait_for_autocad_ready()  # Wait for AutoCAD to be ready
#
#         model_space = active_doc.ModelSpace
#         if not model_space:
#             print_error("ModelSpace is not accessible.")
#             return
#         wait_for_autocad_ready()  # Wait for AutoCAD to be ready
#
#         ext_min, ext_max = calculate_extents(model_space)
#         if ext_min is None or ext_max is None:
#             print_error("Could not calculate extents, exiting.")
#             return
#
#         width = abs(ext_max.x - ext_min.x)
#         height = abs(ext_max.y - ext_min.y)
#
#         print(f"Drawing extents: MinPoint({ext_min.x}, {ext_min.y}), MaxPoint({ext_max.x}, {ext_max.y})")
#         print(f"Width: {width}, Height: {height}")
#
#         unit_name = get_unit_name(active_doc)
#
#         # Define points for the width dimension
#         point1 = APoint(ext_min.x, ext_max.y)
#         point2 = APoint(ext_max.x, ext_max.y)
#         wait_for_autocad_ready()  # Wait for AutoCAD to be ready
#
#         max_text_size = 1
#
#         # Add width dimension
#         try:
#             dimension_width = model_space.AddDimAligned(point1, point2, APoint((ext_min.x + ext_max.x) / 2, ext_max.y + TEXT_OFFSET))
#             dimension_width.TextOverride = f"{round(width, 2)} {unit_name}"
#             max_text_size = max(max_text_size, width / TEXT_SCALE_FACTOR)
#         except Exception as e:
#             print_error(f"Failed to add width dimension: {e}")
#
#         # Define points for the height dimension
#         point1 = APoint(ext_min.x, ext_min.y)
#         point2 = APoint(ext_min.x, ext_max.y)
#         wait_for_autocad_ready()  # Wait for AutoCAD to be ready
#
#         # Add height dimension
#         try:
#             dimension_height = model_space.AddDimAligned(point1, point2, APoint(ext_min.x - TEXT_OFFSET, (ext_min.y + ext_max.y) / 2))
#             dimension_height.TextOverride = f"{round(height, 2)} {unit_name}"
#             max_text_size = max(max_text_size, height / TEXT_SCALE_FACTOR)
#         except Exception as e:
#             print_error(f"Failed to add height dimension: {e}")
#
#         dimension_width.TextHeight = max_text_size
#         dimension_height.TextHeight = max_text_size
#
#         wait_for_autocad_ready()  # Final wait to ensure everything is processed
#         if acad.ActiveDocument:
#             acad.ActiveDocument.Close()
#     except Exception as e:
#         print_error(e)
#
#
# def start_converter():
#     global acad
#     acad = Autocad(create_if_not_exists=True)
#     time.sleep(3)
#     for doc in acad.Application.Documents:
#         doc.Close()
#
#
# def convert_to_pdf(_filepath):
#     add_dimensions_to_drawing(os.path.abspath(_filepath))
#
#     dwg_to_dxf(dwg_dir, dxf_dir)
#
#     dxf_to_pdf(os.path.join(dxf_dir, _filepath.split("\\")[-1].replace(".dwg", ".dxf")))
#
#
# def clean_dwg_files():
#     for filename in os.listdir(dwg_dir):
#         file_path = os.path.join(dwg_dir, filename)
#         try:
#             if os.path.isfile(file_path) or os.path.islink(file_path):
#                 os.unlink(file_path)
#         except Exception as e:
#             print_error('Failed to delete %s. Reason: %s' % (file_path, e))
#
