BULK INSERT valve_details
FROM 'D:\C102641\Valve_Final_Inspection\Valve_Details.csv'
WITH (
    FIRSTROW = 2,
    FIELDTERMINATOR = ',',
    ROWTERMINATOR = '\n',
    TABLOCK
);

