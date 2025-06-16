from z3 import *  # Import Z3 solver for constraint programming
from pathlib import Path  # For handling file paths
from timeit import default_timer as timer  # For measuring execution time
import re  # For regular expressions to parse file contents
from halo import Halo  # For spinner animation during execution

# Start timer to measure the script's execution time
start = timer()

# Define a class to represent the problem instance
class Instance:
    def __init__(self):
        # Initialize instance attributes with default values
        self.number_of_students = 0  # Total number of students
        self.number_of_exams = 0  # Total number of exams
        self.number_of_slots = 0  # Total number of timeslots
        self.number_of_rooms = 0  # Total number of rooms
        self.number_of_invigilators = 0  # Total number of invigilators
        self.room_capacities = []  # List to store room capacities
        self.exams_to_students = []  # List to map exams to students
        self.student_exam_capacity = []  # List to track student exam counts

# Function to read problem instance details from a file
def read_file(filename):
    def read_attribute(name):
        """
        Reads a specific attribute from the file.
        Raises an exception if the expected format is not matched.
        """
        line = f.readline()
        match = re.match(f'{name}:\\s*(\\d+)$', line)
        if match:
            return int(match.group(1))  # Return the numeric value of the attribute
        else:
            raise Exception(f"Could not parse line {line}; expected the {name} attribute")

    # Create an instance object
    instance = Instance()

    # Read the file and populate the instance attributes
    with open(filename) as f:
        instance.number_of_students = read_attribute("Number of students")
        instance.number_of_exams = read_attribute("Number of exams")
        instance.number_of_slots = read_attribute("Number of slots")
        instance.number_of_rooms = read_attribute("Number of rooms")
        instance.number_of_invigilators = 3  # Default number of invigilators

        # Read the room capacities
        for r in range(instance.number_of_rooms):
            instance.room_capacities.append(read_attribute(f"Room {r} capacity"))

        # Read exam-to-student mappings
        while True:
            l = f.readline()
            if l == "":
                break  # End of file
            m = re.match('^\\s*(\\d+)\\s+(\\d+)\\s*$', l)
            if m:
                instance.exams_to_students.append((int(m.group(1)), int(m.group(2))))
            else:
                raise Exception(f'Failed to parse this line: {l}')

        # Initialize student exam capacities
        instance.student_exam_capacity = [0 for _ in range(instance.number_of_exams)]
        for r in instance.exams_to_students:
            instance.student_exam_capacity[r[0]] += 1  # Increment exam count for the student
    return instance

# Function to detect conflicts and suggest resolutions in the scheduling problem
def detect_conflicts(solver, constraint_bools, instance):
    """
    Detect conflicts by identifying unsat cores and suggesting possible resolutions.
    """
    # Check if the problem is unsatisfiable
    if solver.check() == unsat:
        unsat_core = solver.unsat_core()  # Get the unsatisfiable core (conflicting constraints)
        conflict_labels = set()
        for b in unsat_core:
            label = b.decl().name()  # Extract the name of the conflicting constraint
            conflict_labels.add(label)

        # Prepare simplified conflict messages
        conflict_messages = set()
        for label in conflict_labels:
            if 'Invigilator uniqueness' in label or 'Invigilator in range' in label:
                conflict_messages.add("Each invigilator can be assigned to only one exam.")
            elif 'Student' in label and 'non-overlapping' in label:
                conflict_messages.add("Students cannot have overlapping exams.")
            elif 'Room capacity' in label:
                conflict_messages.add("Room capacity exceeded.")
            elif 'Room and time in range' in label:
                conflict_messages.add("Exam times or rooms are out of range.")

        # Aggregate conflicts and suggest adjustments
        suggested_resolutions = set()  # Set of suggested adjustments
        applied_changes = set()  # Track applied changes to prevent duplicates

        # Iterate over conflict messages and suggest resolutions
        for msg in conflict_messages:
            if "Each invigilator can be assigned to only one exam." in msg:
                if 'increase_invigilators' not in applied_changes:
                    instance.number_of_invigilators += 1  # Increase the number of invigilators
                    applied_changes.add('increase_invigilators')
            elif "Students cannot have overlapping exams." in msg:
                if 'increase_timeslot' not in applied_changes:
                    instance.number_of_slots += 1  # Add an extra timeslot
                    applied_changes.add('increase_timeslot')
            elif "Room capacity exceeded." in msg:
                for rm in range(len(instance.room_capacities)):
                    if rm not in applied_changes:
                        instance.room_capacities[rm] += 5  # Increase room capacity
                        applied_changes.add(rm)
            elif "Exam times or rooms are out of range." in msg:
                if 'increase_timeslot' not in applied_changes:
                    instance.number_of_slots += 1  # Add an extra timeslot
                    applied_changes.add('increase_timeslot')

        return conflict_messages, applied_changes  # Return conflicts and applied changes
    return None, None  # Return None if no conflicts are detected


# Solver function to handle the scheduling problem
def solve(instance, multiple_solutions):
    """
    Solves the scheduling problem for the given instance.
    Handles conflicts dynamically and can generate multiple solutions if requested.
    """
    # Initialize variables for conflict detection and tracking adjustments
    conflict_detected = False
    total_conflict_messages = set()
    total_applied_changes = set()
    
    # Store initial instance values to track changes
    initial_invigilators = instance.number_of_invigilators
    initial_time_slots = instance.number_of_slots
    initial_room_capacities = instance.room_capacities.copy()
    
    # Start timer for solving the instance
    instance_start = timer()

    # Infinite loop to iteratively resolve conflicts until a solution is found
    while True:
        # Create a new Z3 solver instance
        s = Solver()

        # Extract instance details
        number_of_students = instance.number_of_students
        number_of_exams = instance.number_of_exams
        number_of_slots = instance.number_of_slots
        number_of_rooms = instance.number_of_rooms
        number_of_invigilators = instance.number_of_invigilators

        # Variables for the problem
        ExamTime = [Int('ExamTime_%d' % ex) for ex in range(number_of_exams)]
        ExamRoom = [Int('ExamRoom_%d' % ex) for ex in range(number_of_exams)]
        ExamInvigilator = [Int('ExamInvigilator_%d' % ex) for ex in range(number_of_exams)]

        # Constraints to enforce scheduling rules
        constraints = []

        # Constraint: Exam times and rooms must be within valid ranges
        for ex in range(number_of_exams):
            constraints.append(("Room and time in range for exam %d" % ex,
                And(
                    ExamTime[ex] >= 0, ExamTime[ex] < number_of_slots,
                    ExamRoom[ex] >= 0, ExamRoom[ex] < number_of_rooms
                )
            ))

        # Constraint: Exams must have unique time and room combinations
        for ex1 in range(number_of_exams):
            for ex2 in range(ex1 + 1, number_of_exams):
                constraints.append(("Unique room and time between exams %d and %d" % (ex1, ex2),
                    Or(
                        ExamTime[ex1] != ExamTime[ex2],
                        ExamRoom[ex1] != ExamRoom[ex2]
                    )
                ))

        # Constraint: Room capacity must not be exceeded
        for ex in range(number_of_exams):
            num_students = instance.student_exam_capacity[ex]
            for rm in range(instance.number_of_rooms):
                constraints.append(("Room capacity for exam %d in room %d" % (ex, rm),
                    Implies(
                        ExamRoom[ex] == rm,
                        num_students <= instance.room_capacities[rm]
                    )
                ))

        # Build exam-to-student and student-to-exam mappings
        exam_students = {}
        student_exams = {}
        for ex, student in instance.exams_to_students:
            exam_students.setdefault(ex, set()).add(student)
            student_exams.setdefault(student, set()).add(ex)

        # Constraint: Students cannot have overlapping exams (adjacent slots)
        for student in range(number_of_students):
            exams = list(student_exams.get(student, []))
            for i in range(len(exams)):
                for j in range(i + 1, len(exams)):
                    ex1 = exams[i]
                    ex2 = exams[j]
                    constraints.append(("Student %d non-overlapping exams %d and %d" % (student, ex1, ex2),
                        Abs(ExamTime[ex1] - ExamTime[ex2]) > 1
                    ))

        # Constraint: Invigilators must be within valid range
        for ex in range(number_of_exams):
            constraints.append(("Invigilator in range for exam %d" % ex,
                And(
                    ExamInvigilator[ex] >= 0,
                    ExamInvigilator[ex] < number_of_invigilators
                )
            ))

        # Constraint: Invigilators must be unique to each exam
        for ex1 in range(number_of_exams):
            for ex2 in range(ex1 + 1, number_of_exams):
                constraints.append(("Invigilator uniqueness between exams %d and %d" % (ex1, ex2),
                    ExamInvigilator[ex1] != ExamInvigilator[ex2]
                ))

        # Add constraints to the solver with assert_and_track for conflict detection
        constraint_bools = {}
        for (label, formula) in constraints:
            b = Bool(label)
            s.assert_and_track(formula, b)
            constraint_bools[label] = b

        # Check for conflicts and attempt to resolve them
        conflict_messages, applied_changes = detect_conflicts(s, constraint_bools, instance)
        if conflict_messages:
            conflict_detected = True
            total_conflict_messages.update(conflict_messages)
            total_applied_changes.update(applied_changes)
            continue  # Retry solving with updated constraints

        # If no conflicts, solve the problem
        else:
            instance_end = timer()
            time_taken = int((instance_end - instance_start) * 1000)
            output_lines.append(f"Time Taken to solve this instance: {time_taken} ms\n")

            # Check if the problem is satisfiable
            if s.check() == sat:
                if conflict_detected:
                    output_lines.append("unsat\n")
                    output_lines.append("Conflicting constraints detected:\n")
                    for msg in total_conflict_messages:
                        output_lines.append(f"  - {msg}\n")
                    output_lines.append("\nSuggested adjustments to resolve conflicts:\n")
                    for change in total_applied_changes:
                        if change == 'increase_invigilators':
                            output_lines.append(f"  - Increased number of invigilators to {instance.number_of_invigilators}.\n")
                        elif change == 'increase_timeslot':
                            increased_slots = instance.number_of_slots - initial_time_slots
                            output_lines.append(f"  - Increased number of time slots by {increased_slots}.\n")
                        else:
                            increased_capacity = instance.room_capacities[change] - initial_room_capacities[change]
                            output_lines.append(f"  - Increased capacity of room {change} by {increased_capacity}.\n")
                    output_lines.append("Suggested changes resolved conflict successfully.\n\n")
                else:
                    output_lines.append("sat\n")

                # Generate solutions
                num_solutions = 0
                max_solutions = 10 if multiple_solutions else 1
                while num_solutions < max_solutions and s.check() == sat:
                    m = s.model()
                    num_solutions += 1
                    output_lines.append(f"Solution {num_solutions}:\n")
                    for ex in range(number_of_exams):
                        output_lines.append(f"   Exam: {ex}  Room: {m.eval(ExamRoom[ex])}  Slot: {m.eval(ExamTime[ex])}  Invigilator: {m.eval(ExamInvigilator[ex])}\n")
                    output_lines.append("\n")
                    # Block the current solution
                    block = [var != m.eval(var) for var in ExamTime + ExamRoom + ExamInvigilator]
                    s.add(Or(block))
                return True
            else:
                output_lines.append("unsat\n")
                output_lines.append("No solution found. You may need to adjust the test instance data to make it satisfiable.\n")
                return False

if __name__ == "__main__":
    # List to store all output lines
    output_lines = []

    # Ask the user whether they want a single or multiple solutions
    choice = input("Do you want to find (1) a single solution or (2) multiple solutions (up to 10)? Enter '1' or '2': ")
    # Determine if multiple solutions are requested based on user input
    multiple_solutions = choice.strip() == '2'

    # Initialize the spinner for a better user experience
    mode_text = "single solution" if not multiple_solutions else "multiple solutions"
    spinner = Halo(text=f"Running solver in {mode_text} mode, please wait...", spinner="dots")
    try:
        spinner.start()  # Start spinner animation

        # Define the directory containing test instances
        tests_dir = Path("test_instances")
        
        # Iterate over all files in the directory in sorted order
        for test in sorted(tests_dir.iterdir()):
            if test.name != ".idea":  # Skip unnecessary files (e.g., IDE config files)
                # Read the test instance from the file
                instance = read_file(str(test))

                # Log the start of processing for the current test instance
                output_lines.append(f"\n{'='*40}\nProcessing {test.name}:\n{'='*40}\n")

                # Solve the current test instance
                result = solve(instance, multiple_solutions)

        # Measure total elapsed time for processing all instances
        end = timer()
        output_lines.append(f'\nElapsed time: {int((end - start) * 1000)} milliseconds\n')

    finally:
        spinner.stop()  # Stop the spinner animation once execution is complete

    # Write all collected output to a file for review
    with open('output.txt', 'w') as output_file:
        output_file.writelines(output_lines)

    # Notify the user that the solutions have been written to the output file
    print("Solutions can be found in output.txt")
    print(f'\nElapsed time: {int((end - start) * 1000)} milliseconds')
