import tkinter as tk
# pyrefly: ignore [missing-import]
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
# pyrefly: ignore [missing-import]
import matplotlib.pyplot as plt
# pyrefly: ignore [missing-import]
from matplotlib import cm  
# pyrefly: ignore [missing-import]
import matplotlib
from collections import defaultdict
from database_manager import db_manager 
matplotlib.use('TkAgg')

def load_defect_counts_from_db():
    counts = defaultdict(int)
    try:
       
        connection = db_manager.get_connection() 
        if connection:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT Defect_type, COUNT(*) 
                FROM inspections 
                WHERE Result = 'Rejected'
                GROUP BY Defect_type
            """)
            results = cursor.fetchall()
            cursor.close()  
            for defect_type, count in results:
                defect_type = defect_type.strip() if defect_type else "Unknown"
                counts[defect_type] += count
        print("Defect counts from DB:", counts)
    except Exception as e:
        print("[DB ERROR]", e)
    return dict(counts)


def update_defect_bar(ax):
    counts = load_defect_counts_from_db()
    ax.clear()

    labels = list(counts.keys())
    values = list(counts.values())

    if not labels:
        ax.text(0.5, 0.5, 'No Rejected Data Found', ha='center', va='center', fontsize=14)
        return

    cmap = cm.get_cmap("viridis")
    colors = [cmap(i / max(len(labels)-1, 1)) for i in range(len(labels))]
    bars = ax.bar(labels, values, color=colors)

    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + 0.1,
            str(height),
            ha='center',
            va='bottom',
            fontsize=10
        )

    ax.set_title("Rejected Defect Counts", fontsize=14)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=10)


def show_dashboard():
    root = tk.Tk()
    root.title("Defect Type Dashboard")
    root.geometry("1200x700")

    fig, ax = plt.subplots(figsize=(10, 6))
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(fill='both', expand=True)

    def refresh():
        update_defect_bar(ax)
        canvas.draw()
        root.after(5000, refresh)  # refresh every 5 seconds

    refresh()
    root.mainloop()


if __name__ == '__main__':
    show_dashboard()
