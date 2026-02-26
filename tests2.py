class Task:
    def __init__(self, task_id, template_id):
        self.task_id = task_id
        self.template_id = template_id
        self.children = []
        self.work_belongs_to_assembly = None
        self.work_belongs_to_order = None

    def add_child(self, child_task):
        self.children.append(child_task)

    def print_children(self, level: int = 0):
        print(f"{'  ' * level}{self.task_id}{' cutting' if False else ''}{' assembly_work' if self.work_belongs_to_assembly else ''}{' order_work' if self.work_belongs_to_order else ''}") #planfix_get(f"task/{self._id}?fields=name&sourceId=0").json()["task"]["name"]
        level += 1
        for child in self.children:
            child.print_children(level)

    # def __repr__(self, level=0):
    #     indent = "  " * level
    #     rep = f"{indent} (child_count={len(self.children)}" # "Task(task_id={self.task_id}, template_id={self.template_id}"
    #     #if self.template_id == 8732007:
    #         #rep += f", work_belongs_to_assembly={self.work_belongs_to_assembly}, work_belongs_to_order={self.work_belongs_to_order}"
    #     rep += ")\n"
    #     for child in self.children:
    #         rep += child.__repr__(level + 1)
    #     return rep


def build_task_tree(task_ids, template_ids, subtask_counts,
                    work_belongs_to_assembly, work_belongs_to_order):
    TEMPLATE_WORK = 8732007
    TEMPLATE_DETAIL = 8732005
    TEMPLATE_ASSEMBLY = 8732191

    tasks = [Task(tid, tmpl_id) for tid, tmpl_id in zip(task_ids, template_ids)]
    root = Task(0, 0)

    index = 0
    sub_index = 0
    leaf_counter = 0

    def parse_subtree(parent_stack):
        nonlocal index, sub_index, leaf_counter
        start_index = index
        task = tasks[index]
        index += 1

        # Work node
        if task.template_id == TEMPLATE_WORK:
            task.work_belongs_to_assembly = work_belongs_to_assembly[leaf_counter]
            task.work_belongs_to_order = work_belongs_to_order[leaf_counter]
            leaf_counter += 1

            if task.work_belongs_to_order:
                root.add_child(task)
            elif task.work_belongs_to_assembly:
                # Find the closest assembly in parent_stack (from top down)
                for parent in reversed(parent_stack):
                    if parent.template_id == TEMPLATE_ASSEMBLY:
                        parent.add_child(task)
                        break
            else:
                # Default: add to current parent (assumed to be Detail)
                parent_stack[-1].add_child(task)

            return None  # Work is already placed, no need to add as child

        # Otherwise it's an Assembly or Detail
        descendant_count = subtask_counts[sub_index]
        sub_index += 1

        # Recursively build subtree
        parent_stack.append(task)
        consumed = 0
        while consumed < descendant_count:
            child = parse_subtree(parent_stack)
            if child is not None:
                task.add_child(child)
            consumed = index - start_index - 1
        parent_stack.pop()
        return task

    # Build top-level tasks
    while index < len(tasks):
        top = parse_subtree([root])
        if top is not None:
            root.add_child(top)

    return root


task_ids = [17157, 17159, 17160, 17161, 17169, 17170, 17175, 17176,
            17162, 17164, 17165, 17171, 17158, 17166, 17167, 17172, 17177]

template_ids = [8732191, 8732191, 8732005, 8732007, 8732007, 8732007, 8732007, 8732007,
                8732191, 8732005, 8732007, 8732007, 8732191, 8732005, 8732007, 8732007, 8732007]

subtask_counts = [11, 6, 3, 3, 2, 3, 2]

work_belongs_to_assembly = [False, False, False, True, True, False, False, False, False, False]
work_belongs_to_order =    [False, False, False, False, False, False, False, False, False, True]

tree = build_task_tree(task_ids, template_ids, subtask_counts,
                       work_belongs_to_assembly, work_belongs_to_order)

tree.print_children()