import time

def run_workflow(nodes, edges):
    results = []

    for node in nodes:
        node_id = node.get("id")
        node_type = node.get("type")

        try:
           
            time.sleep(0.5)

            if node_type == "camera":
                status = "success"
                msg = "Image captured"

            elif node_type == "edge":
                status = "success"
                msg = "Edges detected"

            elif node_type == "measure":
                value = node.get("mock_value", 0)
                min_v = node.get("min")
                max_v = node.get("max")

                if min_v <= value <= max_v:
                    status = "success"
                    msg = f"{node['name']} OK"
                else:
                    status = "fail"
                    msg = f"{node['name']} NG"

            else:
                status = "fail"
                msg = "Unknown node type"

            results.append({
                "node_id": node_id,
                "status": status,
                "message": msg
            })

            if status == "fail":
                break   

        except Exception as e:
            results.append({
                "node_id": node_id,
                "status": "fail",
                "message": str(e)
            })
            break

    return results
