# demo
filter(price > 0.4 & !(category == 'dairy'))
apply(round(price * quantity, 1), revenue)
apply(day(timestamp), d)
group_by([category, d])
window(1h)
aggregate sum(revenue) as total, average(price) as avg_price,
          median(quantity) as median_qty, count(*) as n,
          std(price) as price_std, var(price) as price_var,
          min(price) as min_price, max(price) as max_price
