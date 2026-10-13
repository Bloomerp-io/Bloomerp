# Extend workspace filtering

The goal of this ticket is to extend workspace filtering so that we can allow wrapping.

Assume that we want to build a KPI with the total number of employees. Right now, a query would look something like this:

```sql
SELECT COUNT(*) as number_of_employees FROM employees
```

We'd then select a KPI widget, take the first value, and voila. The problem however is that if we'd want to add a filter based on the department, or whatever, we'd have to instead use

```sql
SELECT department FROM employees
```

Then choose type is KPI, aggregation is count, and set a filter on department. For this small use case this works, but for other more complex aggregations you'd need to hack your way arround. Instead, we'd want to be able to set filters as WHERE clauses outside of the query, which would look something like this:

```sql
<QUERY>

WHERE <filter_1> and <filter_2>
```

If we have a complex revenue calculation, we should therefore be able to set a filter, like quarter outside of the query, without having to integrate this in the query itself.

