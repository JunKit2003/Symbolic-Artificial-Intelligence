import os
import re
from time import time as currenttime
from ortools.sat.python import cp_model
from halo import Halo
import tkinter as tk
from tkinter import filedialog
from helper import transform_output
from ValidatorPro import WorkflowValidator 


def parse_file(filename):
    with open(filename, 'r') as file:
        lines = file.readlines()
    
    # Parse #Steps, #Users, #Constraints
    steps_count = int(lines[0].split(': ')[1])
    users_count = int(lines[1].split(': ')[1])
    constraints_count = int(lines[2].split(': ')[1])
    
    constraints = []
    for line in lines[3:]:
        constraints.append(line.strip())

    return steps_count, users_count, constraints


def build_model(filename):
    """Build and return the model, assignments structure, and relevant parameters without solving.
    This function is used by both single and multi solution solvers."""
    model = cp_model.CpModel()
    steps_count, users_count, constraints = parse_file(filename)

    # Create variables: one for each step and each user indicating assignment (1 or 0)
    user_assignment = [[model.NewBoolVar(f'step_{s + 1}_user_{u + 1}') for u in range(users_count)] for s in range(steps_count)]
    
    # Each step is assigned to exactly one user
    for step in range(steps_count):
        model.AddExactlyOne(user_assignment[step][user] for user in range(users_count))
    
    # Initialize data structures for constraints
    user_authorisations = {}
    user_capacities = {}
    
    # Parse constraints and apply them to the model
    for constraint in constraints:
        parts = constraint.split()
        
        if parts[0] == "Authorisations":
            user = int(parts[1][1:]) - 1  # Adjust to 0-based index
            allowed_steps = [int(step[1:]) - 1 for step in parts[2:]]
            
            if user in user_authorisations:
                print(f"Warning: User u{user + 1} has multiple authorisations defined; only the first will be used.")
                continue
            
            user_authorisations[user] = allowed_steps
            for step in range(steps_count):
                if step not in allowed_steps:
                    model.Add(user_assignment[step][user] == 0)
            print(f"Applied Authorisation constraint for user u{user + 1} on steps {[s + 1 for s in allowed_steps]}")

        elif parts[0] == "Separation-of-duty":
            step1, step2 = int(parts[1][1:]) - 1, int(parts[2][1:]) - 1
            # If step1 is assigned to a user, step2 cannot be assigned to the same user
            for user in range(users_count):
                model.Add(user_assignment[step2][user] == 0).OnlyEnforceIf(user_assignment[step1][user])
            print(f"Applied Separation-of-duty constraint between steps s{step1 + 1} and s{step2 + 1}")

        elif parts[0] == "Binding-of-duty":
            step1, step2 = int(parts[1][1:]) - 1, int(parts[2][1:]) - 1
            # If step1 is assigned to a user, step2 must be assigned to the same user
            for user in range(users_count):
                model.Add(user_assignment[step2][user] == 1).OnlyEnforceIf(user_assignment[step1][user])
            print(f"Applied Binding-of-duty constraint between steps s{step1 + 1} and s{step2 + 1}")

        elif parts[0] == "At-most-k":
            k = int(parts[1])
            step_indices = [int(s[1:]) - 1 for s in parts[2:]]

            # For each user, create a flag that indicates whether the user is assigned to any of the steps
            user_assignment_flag = [model.NewBoolVar(f'atmostk_user_{u + 1}') for u in range(users_count)]
            for user in range(users_count):
                step_user_assignments = [user_assignment[step][user] for step in step_indices]
                model.AddMaxEquality(user_assignment_flag[user], step_user_assignments)
            
            # Sum of flags is less than or equal to k
            model.Add(sum(user_assignment_flag) <= k)
            print(f"Applied At-most-k constraint on steps {[s + 1 for s in step_indices]} with max {k} unique users")

        elif parts[0] == "One-team":
            line = constraint  # Use the entire line for regex parsing
            steps = re.findall(r's(\d+)', line)
            group_steps = [int(s) - 1 for s in steps]  # Adjust to 0-based index

            teams_raw = re.findall(r'\(([^)]+)\)', line)
            team_groups = []
            for team_str in teams_raw:
                users = re.findall(r'u(\d+)', team_str)
                team_groups.append([int(u) - 1 for u in users])  # Adjust to 0-based index

            if not group_steps or not team_groups:
                print(f"Warning: Unable to parse One-team constraint: {line}")
                continue  # Skip to next constraint

            team_vars = [model.NewBoolVar(f'one_team_team_{i}_selected') for i in range(len(team_groups))]

            # Ensure exactly one team is selected
            model.AddExactlyOne(team_vars)

            # If team_var is true for a given team, steps must be assigned to users in that team.
            # If false, steps cannot be assigned to those users.
            for t_idx, team in enumerate(team_groups):
                team_var = team_vars[t_idx]
                for step in group_steps:
                    # If this team is selected, the assigned user for this step must be in the team
                    for user in range(users_count):
                        if user not in team:
                            model.Add(user_assignment[step][user] == 0).OnlyEnforceIf(team_var)
                # Conversely, if this team is not selected, we enforce that steps are not assigned to users in that team
                for step in group_steps:
                    for user in team:
                        model.Add(user_assignment[step][user] == 0).OnlyEnforceIf(team_var.Not())

            print(f"Applied One-team constraint on steps {[s + 1 for s in group_steps]} with teams {[[u + 1 for u in team] for team in team_groups]}")

        elif parts[0] == "User-Capacity":
            user = int(parts[1][1:]) -1
            capacity = int(parts[2])
            user_capacities[user] = capacity
            print(f"Applied User-Capacity constraint: User u{user + 1} has capacity {capacity}")

    # Apply capacities to users
    default_capacity = 20
    for user in range(users_count):
        capacity = user_capacities.get(user, default_capacity)
        assigned_steps = [user_assignment[step][user] for step in range(steps_count)]
        model.Add(sum(assigned_steps) <= capacity)
        print(f"User u{user + 1} capacity set to {capacity}")

    # Handle users with no specified authorisations
    for user in range(users_count):
        if user not in user_authorisations:
            print(f"User u{user + 1} has no specific authorisations; allowed on any step.")

    return model, steps_count, users_count, user_assignment


def SolverSingleSolution(filename):
    model, steps_count, users_count, user_assignment = build_model(filename)
    solver = cp_model.CpSolver()
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False

    with Halo("Solving...", spinner='dots'):
        starttime = int(currenttime() * 1000)
        status = solver.Solve(model)
        endtime = int(currenttime() * 1000)
    
    d = {
        'sat': 'unsat',
        'sol': [],
        'mul_sol': '',
        'exe_time': f"{endtime - starttime}ms"
    }
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        d['sat'] = 'sat'
        solution = []
        for s in range(steps_count):
            for u in range(users_count):
                if solver.Value(user_assignment[s][u]):
                    solution.append(f"s{s + 1}: u{u + 1}")
                    break
        d['sol'] = solution

    print("Solver status:", solver.StatusName(status))
    return d


class MultiSolutionCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, user_assignment, steps_count, users_count, problem_path):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._user_assignment = user_assignment
        self._steps_count = steps_count
        self._users_count = users_count
        self._problem_path = problem_path
        self._solution_count = 0
        self._found_solutions = []

    def OnSolutionCallback(self):
        # Extract current solution
        current_solution = []
        for s in range(self._steps_count):
            for u in range(self._users_count):
                if self.Value(self._user_assignment[s][u]):
                    current_solution.append(f"s{s+1}: u{u+1}")
                    break

        # Check if the solution is unique
        if current_solution not in self._found_solutions:
            # Validate solution immediately
            is_valid = validate_solution(self._problem_path, current_solution)
            if is_valid:
                self._solution_count += 1
                with Halo(text=f"Solution {self._solution_count} found!", spinner='dots') as spinner:
                    spinner.succeed()
                self._found_solutions.append(current_solution)

        # Stop after 10 unique solutions
        if self._solution_count == 10:
            self.StopSearch()


    def get_solutions(self):
        return self._found_solutions


def SolverMultiSolution(filename):
    model, steps_count, users_count, user_assignment = build_model(filename)
    solver = cp_model.CpSolver()
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    # Set a timeout of 4000 seconds (4,000,000 ms) for multi-solution mode
    solver.parameters.max_time_in_seconds = 4000

    collector = MultiSolutionCollector(user_assignment, steps_count, users_count, filename)

    with Halo("Solving (Multi-Solution Mode)...", spinner='dots'):
        starttime = int(currenttime() * 1000)
        status = solver.SearchForAllSolutions(model, collector)
        endtime = int(currenttime() * 1000)

    d = {
        'sat': 'unsat' if len(collector.get_solutions()) == 0 else 'sat',
        'mul_sol': collector.get_solutions(),
        'exe_time': f"{endtime - starttime}ms"
    }

    return d


def validate_solution(problem_path, solution):
    """Run ValidatorPro on the solution before saving or displaying."""
    validator = WorkflowValidator()
    validator.parse_problem(problem_path)

    # Transform solution into a dictionary
    solution_dict = {}
    for line in solution:
        step, user = line.split(': ')
        solution_dict[int(step[1:])] = int(user[1:])

    spinner = Halo(text="Validating solution", spinner="dots")
    spinner.start()

    try:
        is_valid, errors = validator.validate_solution(solution_dict)
        if is_valid:
            spinner.succeed("Validation successful!")
            return True
        else:
            spinner.fail("Validation failed.")
            print("\nSolution Validation Errors:")
            for error in errors:
                print(f"- {error}")
            return False
    except Exception as e:
        spinner.fail(f"Validation error: {e}")
        return False


def save_solution(output_dir, file_name, solution_data):
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, file_name)
    with open(output_path, 'w') as file:
        file.write("\n".join(solution_data))
    print(f"Solution saved to {output_path}")


if __name__ == '__main__':
    base_path = os.path.dirname(__file__)
    instances_path = os.path.join(base_path, 'instances')
    output_base_path = os.path.join(base_path, 'output_doreen')

    # Prompt user for mode selection
    mode = input("Select mode: (S)ingle Solution or (M)ultiple Solutions? ").strip().lower()


    root = tk.Tk()
    root.withdraw()

    root.attributes('-topmost', True)
    root.focus_force()

    spinner = Halo(text="Waiting for file selection", spinner="dots")
    spinner.start()

    try:
        # File selection dialog
        dpath = filedialog.askopenfilename(initialdir=instances_path, title="Select file")
        if dpath:
            spinner.succeed(f"File selected: {dpath}")
            folder_name = os.path.basename(os.path.dirname(dpath))
            file_name = os.path.basename(dpath)

            # Check if the selected file is an example file
            if file_name.startswith("example"):
                folder_name = "examples"

            file_prefix = os.path.splitext(file_name)[0]
            solution_output_dir = os.path.join(output_base_path, folder_name)

            if mode == 'm':
                # Multi-solution mode
                solution_output_file = f"multisolution{file_prefix}.txt"
                d = SolverMultiSolution(dpath)
                if d['sat'] == 'sat':
                    # Multiple solutions found
                    # Combine all solutions into one output
                    all_solutions_output = [d['sat']]
                    sol_index = 1
                    for sol in d['mul_sol']:
                        all_solutions_output.append(f"Solution {sol_index}:")
                        all_solutions_output.extend(sol)
                        sol_index += 1
                    all_solutions_output.append(f"Time Elapsed: {d['exe_time']}")

                    save_solution(solution_output_dir, solution_output_file, all_solutions_output)
                    print("\nAll Solutions:")
                    print("\n".join(all_solutions_output))
                else:
                    # No solution found
                    solution_output = [d['sat'], f"Time Elapsed: {d['exe_time']}"]
                    save_solution(solution_output_dir, solution_output_file, solution_output)
                    print("\nNo solutions found.")
                    print("\n".join(solution_output))

            else:
                # Single solution mode
                solution_output_file = f"solution{file_prefix}.txt"
                d = SolverSingleSolution(dpath)
                if d['sat'] == 'sat':
                    # Validate before saving
                    solution_output = [d['sat']] + d['sol'] + [f"Time Elapsed: {d['exe_time']}"]
                    if validate_solution(dpath, d['sol']):
                        save_solution(solution_output_dir, solution_output_file, solution_output)
                        print("\nSolution:")
                        print("\n".join(solution_output))
                    else:
                        print("\nSolution validation failed. Not saving.")
                        print("\nSolution:")
                        print("\n".join([d['sat']] + d['sol']))
                        print(f"\nTime Elapsed :{d['exe_time']}")
                else:
                    # Save unsat status
                    solution_output = [d['sat']] + d['sol'] + [f"Time Elapsed: {d['exe_time']}"]
                    save_solution(solution_output_dir, solution_output_file, solution_output)
                    print("\nSolution:")
                    print(d['sat'])
                    print(f"\nTime Elapsed :{d['exe_time']}")
        else:
            spinner.fail("No file selected. Exiting.")
    except Exception as e:
        spinner.fail(f"Error occurred: {e}")
