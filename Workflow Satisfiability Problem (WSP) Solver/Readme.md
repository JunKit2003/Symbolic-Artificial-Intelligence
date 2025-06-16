# Workflow Satisfiability Problem (WSP) Solver

This project provides three different implementations for solving the Workflow Satisfiability Problem (WSP) and includes a validator module with a custom GUI for validating and analyzing solutions.

---

## Project Structure

### Main Solver File
- **`WSP_Solver_ortools.py`**  
  The primary solver implementation using Google OR-Tools.

### Alternative Solver Files
- **`WSP_Solver_z3.py`**  
  An alternative solver implementation using the Z3 SMT solver.  
- **`WSP_Solver_Doreen.py`**  
  Based on a formulation provided by the lecturer, serving as an alternative solution approach.

### Validator Module
- **`ValidatorPro.py`**  
  - Responsible for validating solutions before saving them to the output folder.  
  - If the validation fails, the solution is not saved, and the reason for failure is displayed.  
  - **Custom GUI**:  
    - Users can select the problem instance file and the solution file manually.  
    - Alternatively, users can select the desired solver type from a dropdown menu, and the module will automatically detect and validate the corresponding solution file.  
    - If a conflict is detected, the GUI displays the reason for validation failure in red.

---

## Features

1. **Multiple Solver Implementations**:
   - Flexibility to choose between OR-Tools, Z3, or the lecturer's formulation for solving the WSP.
2. **Solution Validation**:
   - Ensures that only valid solutions are saved.
   - Provides detailed feedback in case of conflicts.
3. **Interactive GUI**:
    - In Solver Files:
        - Simplifies the process of selecting problem instance files directly from the solver code, eliminating the need for hardcoded file paths.
        - Users can manually choose the problem instance file through an interactive file selection dialog.
    - In Validator Module:
        - Provides a GUI for selecting problem instance and solution files manually.
        - Includes an automatic detection feature:
        - Users can select the solver type from a dropdown menu.
        - The module will automatically locate and validate the corresponding solution file.
4. **Progress Indicator with Halo Spinner**:
   - **Halo** library is used to display a spinner while the solver is running.
   - Provides visual feedback to assure users that the process is active and the application has not frozen.


---

## Dependencies

All required Python dependencies are listed in the `requirements.txt` file. Install them using:

```bash
pip install -r requirements.txt
