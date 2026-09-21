from bloomerp.dataviews.pivot_table.config import PivotTableDataView
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.definition import BloomerpModelConfig, DetailViewSettings, FieldLayout, LayoutItem, LayoutRow, ModelViewSettings
from bloomerp.modules.users import UsersModule


GROUP_MODEL_CONFIG = BloomerpModelConfig(
    module=UsersModule,
    detail_view_settings=DetailViewSettings(
        layouts=[
            FieldLayout(
                rows=[
                    LayoutRow(
                        columns=2,
                        title="Details",
                        items=[
                            LayoutItem(id="name"),
                            LayoutItem(id="user")
                        ]
                    )
                ]
            )
        ]
    ),
    model_view_settings=ModelViewSettings(
        default_dataviews=[
            TableDataView(
                is_default=True,
                display_fields=["name"]
            ),
            PivotTableDataView(
                name="User counts",
                is_default=False,
                row_fields=["name"],
                value_fields=["user"]
            )           
        ]
    )
    
)