from bloomerp.services.sql_services import SqlExecutor
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.tiles import BaseTileRenderer
import plotly.graph_objects as go
import plotly.io as pio

class AnalyticsTwoDimChartRenderer(BaseTileRenderer):
    def render(self, config:AnalyticsTileConfig):
        # Get the fields
        x_axis = config.fields.get("x_axis")
        y_axis = config.fields.get("y_axis")

        # Get the data
        query_response = SqlExecutor(
            user=None # Permissions should be handled at the tile level, so we can pass None here
        ).execute_query(
            config.query
        )

        # Create the chart
        chart_type = config.opts.get("chart_type", "line")

        fig = go.Figure()

        data = query_response.rows
        x_values = [row[x_axis] for row in data]
        y_values = [row[y_axis] for row in data]

        pass




        
        