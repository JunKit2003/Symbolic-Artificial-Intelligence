# Constraint Satisfiability Problem Solver

This repository contains the implementation of a Constraint Satisfiability Problem (CSP) solver designed for Assessment Timetabling. The solver supports both single-solution and multi-solution modes, incorporates an Automated Conflict Detection and Resolution feature, and stores all solutions in a dedicated output file.

## Features
- **Single and Multi-Solution Modes:**  
  The solver allows users to compute either a single solution or up to 10 solutions.
  
- **Automated Conflict Detection and Resolution:**  
  If the problem is unsatisfiable, the system:
  1. Detects the conflicting constraints.
  2. Suggests possible resolutions.
  3. Tests the resolution and returns the solution if the problem becomes solvable.
  
- **Output Storage:**  
  All solutions (or results of unsatisfiable problems) are stored in `output.txt`.

## Files in the Repository
- **`requirements.txt`:**  
  Contains all necessary Python dependencies. Install them using:
  pip install -r requirements.txt
