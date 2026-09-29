DROP TABLE IF EXISTS defect_type;
CREATE TABLE defect_type (
    Defect_types VARCHAR(50) PRIMARY KEY
    
);
INSERT INTO Defect_type (defect_types)VALUES
('Face Damage'),
('Face Chamfer'),
('Head Damage'),
('Seat Damage'),
('Neck Damage'),
('Stem Damage'),
('Groove Damage'),
('End Chamfer'),
('Tip End'),
('Bend Valve'),
('Crack'),
('Scratch'),
('Discoloration'),
('Ok');
