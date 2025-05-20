## Summary

**DashQt** embeds a Plotly Dash web application in a lightweight Qt window using PySide6’s WebEngine view. It launches a 
local Flask/Dash server on an available port, then displays the app in a `QWebEngineView`. Closing the Qt window 
triggers a clean shutdown of the server, making it easy to package interactive data‑science GUIs in pure Python without 
requiring a full browser.

## Installation

Follow these steps to create a self‑contained Conda environment for DashQt:

1. **Clone the repository**

   ```bash
   git clone https://github.com/gchrisjenkins/dashqt.git
   cd dashqt
   ```

2. **Create & activate a new Conda environment**

   ```bash
   conda create --name dashqt python=3.11 -y
   conda activate dashqt
   ```

3. **Install PySide6 with WebEngine support**

   ```bash
   conda install pyside6 pyqtwebengine -y
   ```

4. **Install Python dependencies**

   ```bash
   pip install dash pandas
   ```

## Notes

* The `pyqtwebengine` package is required to provide `QtWebEngineWidgets`, as it is not included in the base `pyside6` package.
* If you encounter any missing‑module errors for `QtWebEngineWidgets`, verify that `pyqtwebengine` is installed correctly.
* For more information on Dash installation and usage, visit the [official Dash documentation](https://dash.plotly.com/installation).
