use inspection_db;
GO
IF OBJECT_ID('inspections', 'U') IS NOT NULL
    DROP TABLE inspections;
CREATE TABLE inspections (
   
    Part_number VARCHAR(100),
    Image_name VARCHAR(50) NOT NULL,
    ssim_score FLOAT NOT NULL,
    Result VARCHAR(50) NOT NULL,
    Best_match VARCHAR(255),
    Defect_type VARCHAR(100),
    timestamp DATETIME NOT NULL DEFAULT GETDATE()
);

select * from inspections;

