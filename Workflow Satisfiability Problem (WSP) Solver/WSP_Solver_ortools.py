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


def build_model(filename):
    """Build and return the model, assignments, steps_count, and users_count."""
    model = cp_model.CpModel()
    steps_count, users_count, constraints = parse_file(filename)
    
    # Create variables: one for each step
    assignments = [model.NewIntVar(1, users_count, f'step_{i + 1}') for i in range(steps_count)]
    
    user_authorisations = {}
    user_capacities = {}
    one_team_constraints = []

    # Parse constraints
    for constraint in constraints:
        parts = constraint.split()
        
        if parts[0] == "Authorisations":
            user = int(parts[1][1:])
            allowed_steps = [int(step[1:]) for step in parts[2:]]
            
            if user in user_authorisations:
                print(f"Warning: User u{user} has multiple authorisations defined; only the first will be used.")
                continue
            
            user_authorisations[user] = allowed_steps
            for step in range(steps_count):
                if step + 1 not in allowed_steps:
                    model.Add(assignments[step] != user)
            print(f"Applied Authorisation constraint for user u{user} on steps {allowed_steps}")

        elif parts[0] == "Separation-of-duty":
            step1, step2 = int(parts[1][1:]), int(parts[2][1:])
            model.Add(assignments[step1 - 1] != assignments[step2 - 1])
            print(f"Applied Separation-of-duty constraint between steps s{step1} and s{step2}")

        elif parts[0] == "Binding-of-duty":
            step1, step2 = int(parts[1][1:]), int(parts[2][1:])
            model.Add(assignments[step1 - 1] == assignments[step2 - 1])
            print(f"Applied Binding-of-duty constraint between steps s{step1} and s{step2}")

        elif parts[0] == "At-most-k":
            k = int(parts[1])
            step_indices = [int(s[1:]) - 1 for s in parts[2:]]
            group_steps = [assignments[i] for i in step_indices]

            user_vars = [model.NewIntVar(1, users_count, f'atmostk_user_{i}') for i in range(k)]
            
            for i in range(k - 1):
                model.Add(user_vars[i] <= user_vars[i + 1])

            for s in step_indices:
                selector_conditions = []
                for i in range(k):
                    condition = model.NewBoolVar(f'step_{s + 1}_uses_user_{i}')
                    model.Add(assignments[s] == user_vars[i]).OnlyEnforceIf(condition)
                    model.Add(assignments[s] != user_vars[i]).OnlyEnforceIf(condition.Not())
                    selector_conditions.append(condition)
                model.Add(sum(selector_conditions) == 1)
            
            print(f"Applied optimised At-most-k constraint on steps {[s + 1 for s in step_indices]} with max {k} unique users")

        elif parts[0] == "One-team":
            line = constraint
            steps = re.findall(r's(\d+)', line)
            group_steps = [int(s) for s in steps]

            teams_raw = re.findall(r'\(([^)]+)\)', line)
            team_groups = []
            for team_str in teams_raw:
                users = re.findall(r'u(\d+)', team_str)
                team_groups.append([int(u) for u in users])

            if not group_steps or not team_groups:
                print(f"Warning: Unable to parse One-team constraint: {line}")
                continue

            one_team_constraints.append({
                'steps': group_steps,
                'teams': team_groups,
                'team_vars': [],
            })

        elif parts[0] == "User-Capacity":
            user = int(parts[1][1:])
            capacity = int(parts[2])
            user_capacities[user] = capacity
            print(f"Applied User-Capacity constraint: User u{user} has capacity {capacity}")

    # Handle One-Team constraints
    step_constraints = {}
    for idx, otc in enumerate(one_team_constraints):
        teams = otc['teams']
        steps = otc['steps']
        team_vars = []
        for team_idx, team in enumerate(teams):
            team_var = model.NewBoolVar(f'one_team_{idx}_team_{team_idx}_selected')
            team_vars.append(team_var)
        otc['team_vars'] = team_vars

        model.Add(sum(team_vars) == 1)

        for step in steps:
            if step not in step_constraints:
                step_constraints[step] = []
            step_constraints[step].append({
                'constraint_idx': idx,
                'team_vars': team_vars,
                'teams': teams,
            })

        for team_idx, team in enumerate(teams):
            team_var = team_vars[team_idx]
            for step in steps:
                allowed_users_bools = []
                for user in team:
                    user_assigned = model.NewBoolVar(f'step_{step}_user_{user}_team_{idx}_{team_idx}')
                    model.Add(assignments[step - 1] == user).OnlyEnforceIf(user_assigned)
                    model.Add(assignments[step - 1] != user).OnlyEnforceIf(user_assigned.Not())
                    allowed_users_bools.append(user_assigned)
                model.AddBoolOr(allowed_users_bools).OnlyEnforceIf(team_var)

    for step, constraints_list in step_constraints.items():
        if len(constraints_list) > 1:
            for i in range(len(constraints_list)):
                for j in range(i + 1, len(constraints_list)):
                    c1 = constraints_list[i]
                    c2 = constraints_list[j]
                    c1_team_vars = c1['team_vars']
                    c2_team_vars = c2['team_vars']
                    c1_teams = c1['teams']
                    c2_teams = c2['teams']
                    for ti1, team1 in enumerate(c1_teams):
                        for ti2, team2 in enumerate(c2_teams):
                            selected_i = c1_team_vars[ti1]
                            selected_j = c2_team_vars[ti2]
                            overlap = set(team1).intersection(set(team2))
                            if not overlap:
                                model.Add(selected_i + selected_j <= 1)

    # Apply capacities
    default_capacity = 20
    for user in range(1, users_count + 1):
        capacity = user_capacities.get(user, default_capacity)
        
        assigned_steps = []
        for i in range(steps_count):
            is_assigned = model.NewBoolVar(f'step_{i+1}_is_assigned_to_u{user}')
            model.Add(assignments[i] == user).OnlyEnforceIf(is_assigned)
            model.Add(assignments[i] != user).OnlyEnforceIf(is_assigned.Not())
            assigned_steps.append(is_assigned)
        
        model.Add(sum(assigned_steps) <= capacity)
        print(f"User u{user} capacity set to {capacity}")

    # Handle users with no authorisations
    # (No extra constraint needed; it's just a notification)
    steps_authorised = set()
    for auth_steps in user_authorisations.values():
        steps_authorised.update(auth_steps)
    for user in range(1, users_count + 1):
        if user not in user_authorisations:
            print(f"User u{user} has no specific authorisations; allowed on any step.")

    return model, steps_count, users_count, assignments


def SolverSingleSolution(filename):
    model, steps_count, users_count, assignments = build_model(filename)
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
            solution.append(f"s{s+1}: u{solver.Value(assignments[s])}")
        d['sol'] = solution

    print("Solver status:", solver.StatusName(status))
    return d


class MultiSolutionCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, assignments, problem_path):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._assignments = assignments
        self._solution_count = 0
        self._found_solutions = []
        self._problem_path = problem_path

    def OnSolutionCallback(self):
        # Extract current solution
        solution = [f"s{i+1}: u{self.Value(self._assignments[i])}" for i in range(len(self._assignments))]

        # Check if the solution is already in the list
        if solution in self._found_solutions:
            return  # Skip duplicates

        # Validate solution immediately
        is_valid = validate_solution(self._problem_path, solution)
        if is_valid:
            self._solution_count += 1
            # Inform user with a spinner that a new solution is found
            with Halo(text=f"Solution {self._solution_count} found!", spinner='dots') as spinner:
                spinner.succeed()

            self._found_solutions.append(solution)

        # Stop if 10 unique solutions are collected
        if self._solution_count == 10:
            self.StopSearch()


    def get_solutions(self):
        return self._found_solutions


def SolverMultiSolution(filename):
    """Solve the model in multi-solution mode, collecting up to 10 solutions with a timeout."""
    model, steps_count, users_count, assignments = build_model(filename)
    solver = cp_model.CpSolver()
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False

    # Set a timeout of 4000 seconds (4,000,000 ms) for multi-solution mode
    solver.parameters.max_time_in_seconds = 4000

    collector = MultiSolutionCollector(assignments, filename)

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


if __name__ == '__main__':
    base_path = os.path.dirname(__file__)
    instances_path = os.path.join(base_path, 'instances')
    output_base_path = os.path.join(base_path, 'output_ortools')

    # Prompt user for mode selection
    mode = input("Select mode: (S)ingle Solution or (M)ultiple Solutions? ").strip().lower()

    root = tk.Tk()
    root.withdraw()
    
    root.attributes('-topmost', True)
    root.focus_force()

    spinner = Halo(text="Waiting for file selection", spinner="dots")
    spinner.start()

    try:
        dpath = filedialog.askopenfilename(initialdir=instances_path, title="Select file")
        if dpath:
            spinner.succeed(f"File selected: {dpath}")
            folder_name = os.path.basename(os.path.dirname(dpath))
            file_name = os.path.basename(dpath)

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
