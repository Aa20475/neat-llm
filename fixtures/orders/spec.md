# Order normalization task

Convert the supplied JSON array of orders to a normalized JSON array. Return only JSON, without Markdown or explanation. Inputs are valid; all quantities are positive integer strings or integers, and all prices are nonnegative decimal strings in dollars.

For each order:

- Trim surrounding whitespace from `order_id`; preserve its case and leading zeros.
- Trim surrounding whitespace from `email` and lowercase it.
- For each item, trim and uppercase `sku`, and convert `quantity` to a JSON integer.
- Calculate `line_total` as quantity times unit price using exact decimal arithmetic, rounded to two decimal places with ROUND_HALF_UP. Format it as a string with exactly two decimal places.
- Keep every item, including duplicate SKUs. Sort items by normalized SKU in ascending lexicographic order, preserving input order for equal SKUs.
- Set `total` to the sum of the already-rounded line totals, formatted as a string with two decimal places. An empty order has total `"0.00"`.
- Output exactly these order keys: `order_id`, `email`, `items`, `total`. Output exactly these item keys: `sku`, `quantity`, `line_total`. Do not include `unit_price`.

Sort orders by normalized `order_id` in ascending lexicographic order. JSON object-key order does not matter; array order, types, and string formatting do.
