# DAX Measures

The included Power BI file contains `fact_orders`, `fact_sales`, `dim_date`, and `dim_country`. Active relationships link `fact_sales[invoice_date]` (many) to `dim_date[date]` (one), `fact_orders[country]` (many) to `dim_country[country]` (one), and `fact_sales[invoiceno]` (many) to `fact_orders[invoiceno]` (one). The direct relationship from `fact_sales[country]` to `dim_country[country]` is inactive. `dim_product` and `dim_customer` are not loaded in the PBIX. The report uses the `Known Customer Sales` measure below.

## Measure in the included report

```DAX
Known Customer Sales =
SUM ( fact_orders[order_revenue] )
```

## Additional sales model measures

These are reference measures for the expanded sales model. They are not embedded in the saved report.

```DAX
Revenue GBP =
SUM ( fact_sales[revenue] )

Identified Customer Sales GBP =
CALCULATE (
    [Revenue GBP],
    fact_sales[customerid] <> BLANK ()
)

Orders =
DISTINCTCOUNT ( fact_sales[invoiceno] )

Units Sold =
SUM ( fact_sales[quantity] )

Average Order Value GBP =
DIVIDE ( [Revenue GBP], [Orders] )

Identified Customers =
CALCULATE (
    DISTINCTCOUNT ( fact_sales[customerid] ),
    fact_sales[customerid] <> BLANK ()
)

Revenue per Identified Customer GBP =
DIVIDE ( [Identified Customer Sales GBP], [Identified Customers] )

Revenue Previous Month GBP =
CALCULATE (
    [Revenue GBP],
    DATEADD ( dim_date[date], -1, MONTH )
)

Revenue MoM % =
DIVIDE (
    [Revenue GBP] - [Revenue Previous Month GBP],
    [Revenue Previous Month GBP]
)

Repeat Customers =
COUNTROWS (
    FILTER (
        VALUES ( fact_sales[customerid] ),
        NOT ISBLANK ( fact_sales[customerid] )
            && CALCULATE ( DISTINCTCOUNT ( fact_sales[invoiceno] ) ) >= 2
    )
)

Repeat Customer Share =
DIVIDE ( [Repeat Customers], [Identified Customers] )
```

## Target relationships

For a complete sales model, the dimension keys are `dim_date[date]`, `dim_product[stockcode]`, `dim_customer[customerid]`, and `dim_country[country]`. In the included PBIX, the date relationship is active, the country dimension filters `fact_orders`, and the direct country relationship to `fact_sales` is inactive. Product and customer dimension relationships are not present in the saved file. `dim_date` covers the full source period.

## Included report page

The PBIX has a country revenue chart, a monthly revenue trend, and a `Known Customer Sales` KPI. Only `Known Customer Sales` is embedded in the report; the measures above are reference measures for the expanded model.
