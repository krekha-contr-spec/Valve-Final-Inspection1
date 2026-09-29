import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import random

parts = ["P3", "P4"]
locations = ["Location1", "Location2"]
shifts = ["Shift1", "Shift2"]

data = {}
for part in parts:
    data[part] = {}
    for loc in locations:
        data[part][loc] = {}
        for shift in shifts:
            data[part][loc][shift] = {"accepted": 0, "rejected": 0}

def update_charts(ax_pie, ax_bar, canvas, part, location, shift):
    if random.random() > 0.4:
        data[part][location][shift]["accepted"] += 1
    else:
        data[part][location][shift]["rejected"] += 1

    counts = data[part][location][shift]
    accepted = counts["accepted"]
    rejected = counts["rejected"]

    ax_pie.clear()
    labels = ["Accepted", "Rejected"]
    values = [accepted, rejected]
    wedges, texts, autotexts = ax_pie.pie(
        values, labels=labels, autopct='%1.0f%%',
        colors=['#B6F500', 'red'], startangle=90,
        textprops={'fontsize': 12, 'color': 'white'}
    )
    ax_pie.set_title(f"Inspection Results\n{part} - {location} - {shift}", fontsize=14)
    for text in autotexts:
        text.set_color('white')
        text.set_fontsize(12)
        text.set_fontweight('bold')
    ax_pie.legend(wedges, labels, loc="upper left")

    ax_bar.clear()
    ax_bar.bar(labels, values, color=['#56DFCF', 'red'])
    ax_bar.set_ylabel("Count")
    ax_bar.set_title("Accepted vs Rejected", fontsize=14)

    canvas.draw()

def show_dashboard():
    window = tk.Tk()
    window.title("Inspection Dashboard")
    window.geometry("1000x600")

    tk.Label(window, text="Select Part:").pack()
    part_var = tk.StringVar(value=parts[0])
    part_menu = ttk.Combobox(window, textvariable=part_var, values=parts)
    part_menu.pack()

    tk.Label(window, text="Select Location:").pack()
    location_var = tk.StringVar(value=locations[0])
    location_menu = ttk.Combobox(window, textvariable=location_var, values=locations)
    location_menu.pack()

    tk.Label(window, text="Select Shift:").pack()
    shift_var = tk.StringVar(value=shifts[0])
    shift_menu = ttk.Combobox(window, textvariable=shift_var, values=shifts)
    shift_menu.pack()

    tk.Label(window, text="Select Time Filter:").pack()
    time_filter_var = tk.StringVar(value="daily")
    filter_menu = ttk.Combobox(window, textvariable=time_filter_var,
                               values=["daily", "weekly", "monthly", "yearly"])
    filter_menu.pack()

    fig, (ax_pie, ax_bar) = plt.subplots(1, 2, figsize=(10, 5))
    canvas = FigureCanvasTkAgg(fig, master=window)
    canvas.get_tk_widget().pack(expand=True, fill="both")

    def refresh():
        update_charts(ax_pie, ax_bar, canvas,
                      part=part_var.get(),
                      location=location_var.get(),
                      shift=shift_var.get())
        window.after(5000, refresh)

    refresh()
    window.mainloop()

if __name__ == "__main__":
    show_dashboard()
