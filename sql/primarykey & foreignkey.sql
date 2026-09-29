ALTER TABLE inspections
ADD CONSTRAINT FK_Inspections_ValveDetails
FOREIGN KEY (Part_Number)
REFERENCES Valve_Details(Part_Number);

EXEC sp_pkeys'inspections';
EXEC sp_pkeys'Valve_Details';
EXEC sp_fkeys'Valve_Details';



