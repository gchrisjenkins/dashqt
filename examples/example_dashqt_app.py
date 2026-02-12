import logging
from typing import Callable

import pandas as pd
import plotly.express as px
from dash import html, dcc, Output, Input
from dash.development.base_component import Component
from plotly.graph_objs import Figure

from dashqt import EmbeddedDashApplication


class ExampleDashApp(EmbeddedDashApplication):

    def __init__(self):
        super().__init__(name=type(self).__name__)
        self._df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/gapminder_unfiltered.csv")

    def _build_layout(self) -> Component | list[Component]:

        return [
            html.H1(children="Population Growth", style={"textAlign": "center"}),
            dcc.Dropdown(self._df.country.unique(), "United States", id="dropdown-selection"),
            dcc.Graph(id="graph-content"),
        ]

    def _build_callbacks(self) -> list[tuple[Output | list[Output], Input | list[Input], Callable[..., Figure]]]:

        return [(
            Output("graph-content", "figure"),
            Input("dropdown-selection", "value"),
            self._on_update_graph_content,
        )]

    def _on_update_graph_content(self, value):
        filtered_df = self._df[self._df.country == value]
        return px.line(filtered_df, x="year", y="pop")


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)s | %(threadName)s | %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # Reduce noise from dependencies while keeping application logs verbose.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("Qt").setLevel(logging.INFO)

    app = ExampleDashApp()
    app.run_forever()  # Blocks until the browser window closes.

    logging.shutdown()

    print(f"{type(app).__name__} exited with code: {app.exit_code}")
    raise SystemExit(app.exit_code)
