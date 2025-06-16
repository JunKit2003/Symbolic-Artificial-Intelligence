import os
import re
from tkinter import Tk, Button, Label, filedialog, StringVar, OptionMenu
from typing import Dict, List, Tuple
from collections import defaultdict

def get_relative_path(relative_path: str) -> str:
    """Get an absolute path relative to the directory of this script."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, relative_path)


class WorkflowValidator:
    def __init__(self):
        self.steps_count = 0
        self.users_count = 0
        self.constraints_count = 0
        self.authorizations = defaultdict(list)  # User -> allowed steps
        self.separation_duties = []  # Pairs of steps
        self.binding_duties = []  # Pairs of steps
        self.at_most_k = []  # (k, steps)
        self.one_team = []  # (steps, teams)
        self.default_capacity = 20  # Default capacity for users
        self.user_capacities = {}  # Store user capacities if defined

    def parse_problem(self, filepath: str):
        """Parse the problem instance and populate constraints."""
        with open(filepath, 'r') as file:
            lines = file.readlines()

        # Parse header
        self.steps_count = int(lines[0].split(': ')[1])
        self.users_count = int(lines[1].split(': ')[1])
        self.constraints_count = int(lines[2].split(': ')[1])

        # Parse constraints
        for line in lines[3:]:
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if parts[0] == "Authorisations":
                user = int(parts[1][1:])
                steps = [int(s[1:]) for s in parts[2:]]
                self.authorizations[user] = steps

            elif parts[0] == "Separation-of-duty":
                self.separation_duties.append((int(parts[1][1:]), int(parts[2][1:])))

            elif parts[0] == "Binding-of-duty":
                self.binding_duties.append((int(parts[1][1:]), int(parts[2][1:])))

            elif parts[0] == "At-most-k":
                k = int(parts[1])
                steps = [int(s[1:]) for s in parts[2:]]
                self.at_most_k.append((k, steps))

            elif parts[0] == "One-team":
                # Parse steps and teams
                steps = [int(s) for s in re.findall(r's(\d+)', " ".join(parts))]
                teams_raw = re.findall(r'\(([^)]+)\)', " ".join(parts))
                teams = [[int(u[1:]) for u in team.split()] for team in teams_raw]
                self.one_team.append((steps, teams))

            elif parts[0] == "User-Capacity":
                user = int(parts[1][1:])
                capacity = int(parts[2])
                self.user_capacities[user] = capacity
                print(f"Parsed capacity for User u{user}: {capacity}")

    def parse_solution(self, filepath: str) -> Tuple[Dict[int, int], bool]:
        """Parse solution file and return step-to-user assignments."""
        assignments = {}
        with open(filepath, 'r') as file:
            lines = file.readlines()

        # Check for unsat solutions
        for line in lines:
            if "unsat" in line.lower():
                return {}, True  # Return unsat flag

        for line in lines:
            line = line.strip()
            if not line or ': ' not in line:  # Skip invalid lines
                continue
            try:
                step, user = line.split(': ')
                assignments[int(step[1:])] = int(user[1:])
            except ValueError:
                print(f"Skipping invalid line in solution file: {line}")

        return assignments, False

    def validate_solution(self, assignments: Dict[int, int]) -> Tuple[bool, List[str]]:
        """Run all validations and return the results."""
        errors = []

        def validate_authorizations():
            for step, user in assignments.items():
                if user in self.authorizations and step not in self.authorizations[user]:
                    errors.append(f"Authorization violation: User u{user} is not authorized for step s{step}.")

        def validate_separation_of_duty():
            for step1, step2 in self.separation_duties:
                if assignments.get(step1) == assignments.get(step2):
                    errors.append(f"Separation-of-duty violation: Steps s{step1} and s{step2} assigned to the same user.")

        def validate_binding_of_duty():
            for step1, step2 in self.binding_duties:
                if assignments.get(step1) != assignments.get(step2):
                    errors.append(f"Binding-of-duty violation: Steps s{step1} and s{step2} assigned to different users.")

        def validate_at_most_k():
            for k, steps in self.at_most_k:
                assigned_users = {assignments[s] for s in steps if s in assignments}
                if len(assigned_users) > k:
                    errors.append(f"At-most-{k} violation: More than {k} users assigned to steps {steps}.")

        def validate_one_team():
            for steps, teams in self.one_team:
                assigned_users = [assignments[s] for s in steps if s in assignments]
                # Check if all assigned users form a valid team
                if not any(all(user in team for user in assigned_users) for team in teams):
                    errors.append(f"One-team violated: Steps {steps} assigned users {assigned_users} do not match any valid team {teams}.")

        def validate_user_capacity():
            # Ensure no user is assigned more than the default capacity of steps.
            for user in range(1, self.users_count + 1):
                assigned_steps = [step for step, assigned_user in assignments.items() if assigned_user == user]
                # Check if a specific capacity is defined for this user, otherwise use default
                capacity = self.user_capacities.get(user, self.default_capacity)
                if len(assigned_steps) > capacity:
                    errors.append(
                        f"User-Capacity violation: User u{user} assigned to {len(assigned_steps)} steps, exceeding capacity {capacity}.")

        # Run all validations
        validate_authorizations()
        validate_separation_of_duty()
        validate_binding_of_duty()
        validate_at_most_k()
        validate_one_team()
        validate_user_capacity()

        return len(errors) == 0, errors


def autodetect_solution_path(problem_path: str, solver_folder: str) -> str:
    """Determine the solution file path based on the problem file path and chosen solver folder."""
    # Convert solver_folder to absolute path relative to the script
    solver_folder = get_relative_path(solver_folder)

    base_dir, problem_file = os.path.split(problem_path)
    sub_dir = os.path.basename(base_dir)

    solution_dir = os.path.join(solver_folder, sub_dir)
    solution_file = f"solution{problem_file}"
    solution_path = os.path.join(solution_dir, solution_file)

    # Debug prints to verify constructed path
    print("Autodetect Debug:")
    print(f"problem_path: {problem_path}")
    print(f"solver_folder (resolved): {solver_folder}")
    print(f"sub_dir: {sub_dir}")
    print(f"solution_dir: {solution_dir}")
    print(f"solution_file: {solution_file}")
    print(f"solution_path: {solution_path}, Exists: {os.path.exists(solution_path)}")

    return solution_path if os.path.exists(solution_path) else None


def main():
    def select_problem_file():
        """Open file explorer to select problem file."""
        initial_dir = get_relative_path("instances")  # start in the instances directory
        file_path = filedialog.askopenfilename(initialdir=initial_dir, title="Select Problem File")
        print(f"Initial directory for problem file dialog: {initial_dir}")

        if file_path:
            problem_label.config(text=f"Problem File: {os.path.basename(file_path)}")
            selected_files["problem"] = file_path
            result_label.config(text="", fg="black")
            # Autodetect corresponding solution file from chosen solver folder
            solver_folder = selected_files.get("solver_folder", "output_ortools")
            solution_path = autodetect_solution_path(file_path, solver_folder)
            if solution_path:
                solution_label.config(text=f"Solution File: {os.path.basename(solution_path)}")
                autodetect_status.config(text="Autodetect Successful", fg="green")
                selected_files["solution"] = solution_path
            else:
                solution_label.config(text="Solution File: Not Found (select manually)")
                autodetect_status.config(text="Autodetect Unsuccessful, Please select manually", fg="red")
                selected_files["solution"] = None

    def select_solution_file():
        """Open file explorer to select solution file."""
        initial_dir = get_relative_path("output_ortools")
        file_path = filedialog.askopenfilename(initialdir=initial_dir, title="Select Solution File")
        result_label.config(text="", fg="black")
        if file_path:
            solution_label.config(text=f"Solution File: {os.path.basename(file_path)}")
            autodetect_status.config(text="", fg="black")  # Clear autodetect status
            selected_files["solution"] = file_path

    def run_validation():
        """Run validation on the selected files."""
        problem_file = selected_files.get("problem")
        solution_file = selected_files.get("solution")

        if not problem_file or not solution_file:
            result_label.config(text="Please select both files!")
            return

        validator = WorkflowValidator()
        validator.parse_problem(problem_file)
        assignments, is_unsat = validator.parse_solution(solution_file)

        if is_unsat:
            result_label.config(text="SOLUTION IS UNSAT", fg="red")
            return

        is_valid, errors = validator.validate_solution(assignments)

        if is_valid:
            result_label.config(text="Solution is valid!", fg="green")
        else:
            result_label.config(text="Solution is invalid.\n" + "\n".join(errors), fg="red")

    def update_solver_folder(*args):
        selected_files["solver_folder"] = solver_var.get()
        # If a problem is already selected, try re-autodetect with the new solver folder
        problem_file = selected_files.get("problem")
        if problem_file:
            solver_folder = selected_files.get("solver_folder", "output_ortools")
            solution_path = autodetect_solution_path(problem_file, solver_folder)
            if solution_path:
                solution_label.config(text=f"Solution File: {os.path.basename(solution_path)}")
                autodetect_status.config(text="Autodetect Successful", fg="green")
                selected_files["solution"] = solution_path
            else:
                solution_label.config(text="Solution File: Not Found (select manually)")
                autodetect_status.config(text="Autodetect Unsuccessful, Please select manually", fg="red")
                selected_files["solution"] = None

    # GUI setup
    root = Tk()
    root.title("Workflow Validator")
    root.geometry("300x450") 

    selected_files = {}

    # Solver folder selection
    solver_var = StringVar(root)
    solver_var.set("output_ortools")  # default selection
    solver_options = ["output_ortools", "output_z3", "output_doreen"]
    solver_dropdown = OptionMenu(root, solver_var, *solver_options)
    solver_dropdown.config(width=20)
    solver_dropdown.pack(pady=5)
    solver_var.trace("w", update_solver_folder)

    Button(root, text="Select Problem File", command=select_problem_file).pack(pady=5)
    problem_label = Label(root, text="Problem File: None")
    problem_label.pack()

    Button(root, text="Select Solution File", command=select_solution_file).pack(pady=5)
    solution_label = Label(root, text="Solution File: None")
    solution_label.pack()

    autodetect_status = Label(root, text="", fg="black")
    autodetect_status.pack()

    Button(root, text="Run Validation", command=run_validation).pack(pady=10)
    result_label = Label(root, text="", wraplength=280, justify="left")
    result_label.pack()

    root.mainloop()


if __name__ == "__main__":
    main()
