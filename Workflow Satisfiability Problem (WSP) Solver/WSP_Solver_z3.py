import os
import re
from time import time as currenttime
from halo import Halo
import tkinter as tk
from tkinter import filedialog
from z3 import Solver, Int, Bool, Or, And, Not, If, Sum, Implies, sat, unknown

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
        line_stripped = line.strip()
        if line_stripped:
            constraints.append(line_stripped)
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


def build_z3_model(filename):
    """Builds the Z3 model based on the given file, returns solver, assignments, steps_count, users_count."""
    solver = Solver()
    steps_count, users_count, constraints = parse_file(filename)

    # Create variables: one for each step
    assignments = [Int(f'step_{i + 1}') for i in range(steps_count)]
    for i in range(steps_count):
        solver.add(assignments[i] >= 1, assignments[i] <= users_count)

    user_authorisations = {}
    user_capacities = {}
    one_team_constraints = []
    at_most_k_constraints = []

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
                if (step + 1) not in allowed_steps:
                    solver.add(assignments[step] != user)
            print(f"Applied Authorisation constraint for user u{user} on steps {allowed_steps}")

        elif parts[0] == "Separation-of-duty":
            step1, step2 = int(parts[1][1:]), int(parts[2][1:])
            solver.add(assignments[step1 - 1] != assignments[step2 - 1])
            print(f"Applied Separation-of-duty constraint between steps s{step1} and s{step2}")

        elif parts[0] == "Binding-of-duty":
            step1, step2 = int(parts[1][1:]), int(parts[2][1:])
            solver.add(assignments[step1 - 1] == assignments[step2 - 1])
            print(f"Applied Binding-of-duty constraint between steps s{step1} and s{step2}")

        elif parts[0] == "At-most-k":
            k = int(parts[1])
            step_indices = [int(s[1:]) - 1 for s in parts[2:]]
            at_most_k_constraints.append((k, step_indices))
            print(f"Found At-most-k constraint on steps {[s + 1 for s in step_indices]} with max {k} unique users")

        elif parts[0] == "One-team":
            line = constraint
            steps_match = re.findall(r's(\d+)', line)
            group_steps = [int(s) for s in steps_match]

            teams_raw = re.findall(r'\(([^)]+)\)', line)
            team_groups = []
            for team_str in teams_raw:
                users_matched = re.findall(r'u(\d+)', team_str)
                team_groups.append([int(u) for u in users_matched])

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

    # Process One-Team constraints
    step_constraints = {}
    for idx, otc in enumerate(one_team_constraints):
        teams = otc['teams']
        steps = otc['steps']
        team_vars = [Bool(f'one_team_{idx}_team_{t_idx}_selected') for t_idx, _ in enumerate(teams)]
        otc['team_vars'] = team_vars

        # Exactly one team is selected
        solver.add(Sum([If(tv, 1, 0) for tv in team_vars]) == 1)

        # Track constraints per step
        for step in steps:
            if step not in step_constraints:
                step_constraints[step] = []
            step_constraints[step].append({
                'constraint_idx': idx,
                'team_vars': team_vars,
                'teams': teams,
            })

        # If a team is selected, the assigned user must be from that team
        for team_idx, team in enumerate(teams):
            team_var = team_vars[team_idx]
            for step in steps:
                solver.add(Implies(team_var, Or([assignments[step - 1] == u for u in team])))

    # Handle overlapping steps between One-Team constraints
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
                                solver.add(Not(And(selected_i, selected_j)))

    # Apply capacities
    default_capacity = 20
    for user in range(1, users_count + 1):
        capacity = user_capacities.get(user, default_capacity)
        solver.add(Sum([If(assignments[i] == user, 1, 0) for i in range(steps_count)]) <= capacity)
        print(f"User u{user} capacity set to {capacity}")

    # Authorisations: no special handling needed if not given, allowed on any step
    for user in range(1, users_count + 1):
        if user not in user_authorisations:
            print(f"User u{user} has no specific authorisations; allowed on any step.")

    # Encode At-most-k constraints
    constraint_counter = 0
    for (k, step_indices) in at_most_k_constraints:
        user_vars = [Int(f'atmostk_{constraint_counter}_{j}') for j in range(k)]
        for uv in user_vars:
            solver.add(uv >= 1, uv <= users_count)
        # Symmetry breaking
        for i in range(k - 1):
            solver.add(user_vars[i] <= user_vars[i + 1])

        # Each step in this group must be assigned to one of the user_vars
        for s in step_indices:
            solver.add(Or([assignments[s] == uv for uv in user_vars]))

        constraint_counter += 1
        print(f"Applied At-most-k constraint on steps {[s + 1 for s in step_indices]} with max {k} unique users")

    return solver, assignments, steps_count, users_count


def solve_single_solution(filename):
    """Solve the model in single-solution mode."""
    solver, assignments, steps_count, users_count = build_z3_model(filename)

    with Halo("Solving...", spinner='dots'):
        starttime = int(currenttime() * 1000)
        check_status = solver.check()
        endtime = int(currenttime() * 1000)

    d = {
        'sat': 'unsat',
        'sol': [],
        'exe_time': f"{endtime - starttime}ms"
    }

    if check_status == sat:
        d['sat'] = 'sat'
        model = solver.model()
        solution = [f"s{i+1}: u{model[assignments[i]].as_long()}" for i in range(steps_count)]
        d['sol'] = solution

    print("Solver status:", "sat" if check_status == sat else "unsat")
    return d


def solve_multi_solution(filename):
    """Solve the model in multi-solution mode, collecting up to 10 solutions with a 4,000,000 ms timeout."""
    solver, assignments, steps_count, users_count = build_z3_model(filename)

    # Set a timeout of 4,000,000 ms for multi-solution mode
    solver.set(timeout=4000000)

    solutions_found = []
    solution_count = 0

    # We'll iterate up to 10 solutions
    with Halo("Solving (Multi-Solution Mode)...", spinner='dots') as h:
        starttime = int(currenttime() * 1000)
        
        while solution_count < 10:
            status = solver.check()
            if status == sat:
                model = solver.model()
                solution = [f"s{i+1}: u{model[assignments[i]].as_long()}" for i in range(steps_count)]
                # Validate the solution
                if validate_solution(filename, solution):
                    solution_count += 1
                    # Show that a new solution is found
                    with Halo(text=f"Solution {solution_count} found!", spinner='dots') as spinner:
                        spinner.succeed()
                    solutions_found.append(solution)

                # Add a constraint to exclude the current solution for the next iteration
                # Force at least one step assignment to differ
                exclude = []
                for i in range(steps_count):
                    exclude.append(assignments[i] != model[assignments[i]])
                solver.add(Or(exclude))

            elif status == unknown:
                # Timeout or other issue
                print("Solver returned unknown (likely timeout). Returning partial solutions.")
                break
            else:
                # unsat: no more solutions
                break

        endtime = int(currenttime() * 1000)

    d = {
        'sat': 'unsat' if len(solutions_found) == 0 else 'sat',
        'mul_sol': solutions_found,
        'exe_time': f"{endtime - starttime}ms"
    }

    return d


if __name__ == '__main__':
    base_path = os.path.dirname(__file__)
    instances_path = os.path.join(base_path, 'instances')
    output_base_path = os.path.join(base_path, 'output_z3')

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
                d = solve_multi_solution(dpath)
                if d['sat'] == 'sat':
                    # Multiple solutions found
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
                d = solve_single_solution(dpath)
                if d['sat'] == 'sat':
                    solution_output = [d['sat']] + d['sol'] + [f"Time Elapsed: {d['exe_time']}"]
                    # Validate the solution before saving or printing
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
                    solution_output = [d['sat']] + d['sol'] + [f"Time Elapsed: {d['exe_time']}"]
                    save_solution(solution_output_dir, solution_output_file, solution_output)
                    print("\nSolution:")
                    print(d['sat'])
                    print(f"\nTime Elapsed :{d['exe_time']}")
        else:
            spinner.fail("No file selected. Exiting.")
    except Exception as e:
        spinner.fail(f"Error occurred: {e}")
