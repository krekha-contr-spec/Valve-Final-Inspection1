-- 🔹 Daily (today)
SELECT * 
FROM inspections
WHERE Result = 'Rejected'
  AND [timestamp] >= CAST(GETDATE() AS DATE);

-- 🔹 Weekly (last 7 days)
SELECT * 
FROM inspections
WHERE Result = 'Rejected'
  AND [timestamp] >= DATEADD(DAY, -7, GETDATE());

-- 🔹 3 Months once (last 90 days)
SELECT * 
FROM inspections
WHERE Result = 'Rejected'
  AND [timestamp] >= DATEADD(MONTH, -3, GETDATE());

-- 🔹 6 Months once (last 180 days)
SELECT * 
FROM inspections
WHERE Result = 'Rejected'
  AND [timestamp] >= DATEADD(MONTH, -6, GETDATE());

-- 🔹 Yearly (last 365 days)
SELECT * 
FROM inspections
WHERE Result = 'Rejected'
  AND [timestamp] >= DATEADD(YEAR, -1, GETDATE());

