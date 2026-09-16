# Rim Analysis Tool

Rim Analysis Tool is a small Python GUI application for measuring fluorescence intensity around the membrane of approximately circular or elliptical vesicles.

The program was developed for fluorescence microscopy images of liposomes where the signal of interest is localized at, or close to, the vesicle membrane. The user manually places an elliptical or circular region of interest (ROI) on the vesicle rim, adjusts it interactively, and extracts the fluorescence intensity as a function of angular position around the membrane.

The emphasis is on a simple, transparent workflow: image display settings such as contrast, brightness, zoom, and panning are used only to make vesicles easier to see and select. Intensity measurements are always performed on the original image data.

## Features

- Interactive circular or elliptical rim selection
- Adjustable ROI handles for fine positioning
- Circular selection with `Shift`
- Symmetric or uniform ROI resizing with keyboard modifiers
- Mouse-wheel zoom
- Right-mouse panning
- Fit-to-window view
- Automatic display contrast enhancement
- Manual brightness and contrast adjustment
- Reset to the original, unenhanced display
- Adjustable rim thickness
- Optional smoothing of the resulting intensity profile
- Multiple plot-color choices
- CSV export of raw intensity values
- Export of the intensity profile as PNG or SVG
- Automatic text log containing analysis settings and summary statistics

## Measurement principle

The ROI defines an ellipse around the vesicle membrane. The program samples the image at 360 angular positions around that ellipse.

For each angular position, pixels are sampled across the selected rim thickness (and optionally averaged). This produces an intensity profile as a function of angle from 0 to 360 degrees.

Importantly, viewer operations do **not** modify the data used for analysis. Automatic contrast, manual brightness/contrast changes, zooming, and panning affect only how the image is displayed.

## Requirements

Rim Analysis Tool requires Python 3 and the following third-party packages:

- NumPy
- Matplotlib
- OpenCV
- Pillow

Tkinter is part of the standard Python installation on Windows and is used for the graphical interface.

A Python virtual environment is recommended.

## Installation

### Windows

Clone or download the repository, open PowerShell in the repository directory, and create a virtual environment:

```powershell
py -3.12 -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the required packages:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Then start the program:

```powershell
python RimAnalysisTool.py
```

If PowerShell prevents virtual-environment activation because of the execution policy, either use Command Prompt or allow locally created scripts for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Basic workflow

1. Click **Load Image** and select a supported microscopy image.
2. Adjust the viewer if necessary using **Auto Contrast**, the brightness/contrast controls, or **Reset B/C**.
3. Draw an ellipse around the vesicle membrane using the left mouse button.
4. Refine the ROI using the handles.
5. Set the desired **Rim Thickness**.
6. Optionally enable curve smoothing and choose a plot color.
7. Click **Process Image**.
8. Inspect the generated rim-intensity profile.
9. Save the numerical data with **Save CSV** and/or save the plot with **Save Plot Image**.

Changing the ROI or rim thickness invalidates the previous result, preventing old measurements from being saved accidentally.

## Viewer controls

| Control | Action |
|---|---|
| Mouse wheel | Zoom |
| Right-mouse drag | Pan image |
| `+` / `-` | Zoom in / out |
| `0` | Reset zoom to 1:1 |
| `F` | Fit image to viewer |
| `R` | Original display / reset brightness and contrast |

## ROI controls

| Control | Action |
|---|---|
| Left mouse drag | Draw ellipse |
| `Shift` + left mouse drag | Draw circle |
| Drag handle | Adjust one side of ROI |
| `Shift` + handle | Symmetric adjustment |
| `Shift` + `Alt` + handle | Uniform circular adjustment |
| `D` | Clear/redraw selection |

## Output

### CSV

The CSV file contains:

```text
Angle (degrees),Intensity
```

with one intensity value for each sampled angular position.

### Analysis log

When a CSV file is saved, a text log is created alongside it. The log records the source image, analysis settings, viewer settings, and summary statistics such as mean, minimum, maximum, and standard deviation.

### Plot

The intensity profile can be exported as PNG or SVG.

## Supported image formats

The file dialog currently accepts:

- PNG
- JPEG
- TIFF

Images are loaded using OpenCV with the original bit depth preserved whenever supported. TIFF is recommended to preserve 16-bit intensity values.

## Notes on image display

Fluorescence images can be difficult to inspect directly, particularly when the useful signal occupies only a small part of the available intensity range. Therefore, images open with automatic contrast enhancement for display.

This enhancement does **not** modify the original image or the measured fluorescence values.

The **Reset B/C** button switches the viewer back to an unenhanced representation with neutral brightness and contrast.

## Intended use

This program was developed as a research analysis utility for fluorescence microscopy data. It is not intended for clinical or diagnostic use.

## License

MIT



The `requirements.txt` file lists the Python packages required to run the program.
