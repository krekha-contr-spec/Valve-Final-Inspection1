
SELECT Defect_type, COUNT(*) AS TotalRejected
FROM inspections
WHERE Result = 'Rejected'
  AND timestamp >= DATEADD(MONTH, -3, GETDATE())
GROUP BY Defect_type;

