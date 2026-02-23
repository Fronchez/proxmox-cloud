import { useState, useEffect } from "react";
import { api, removeToken } from "../api";
import { useNavigate } from "react-router-dom";

export default function Dashboard() {
  const [vms, setVMs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [vmType, setVmType] = useState("qemu");
  const [os, setOs] = useState("ubuntu-22.04");
  const [cpu, setCpu] = useState(1);
  const [memory, setMemory] = useState(2048);
  const [disk, setDisk] = useState(10);
  const navigate = useNavigate();

  const fetchVMs = async () => {
    try {
      setLoading(true);
      const [resQEMU, resLXC] = await Promise.all([
        api.get("/vms/"),
        api.get("/lxc/"),
      ]);
      setVMs([...(resQEMU.data || []), ...(resLXC.data || [])]);
    } catch (err) {
      console.error("Failed to fetch VMs:", err);
    } finally {
      setLoading(false);
    }
  };

  const createVM = async (e) => {
    e.preventDefault();
    try {
      const endpoint = vmType === "qemu" ? "/vms/" : "/lxc/";
      await api.post(endpoint, {
        name,
        type: vmType,
        os,
        cpu: parseInt(cpu),
        memory: parseInt(memory),
        disk: parseInt(disk),
      });
      setName("");
      fetchVMs();
    } catch (err) {
      alert(`Failed to create: ${err.response?.data?.detail || err.message}`);
    }
  };

  const deleteVM = async (vmid, type) => {
    if (!confirm(`Are you sure you want to delete VM ${vmid}?`)) return;
    try {
      const endpoint = type === "qemu" ? `/vms/${vmid}` : `/lxc/${vmid}`;
      await api.delete(endpoint);
      fetchVMs();
    } catch (err) {
      alert(`Failed to delete: ${err.response?.data?.detail || err.message}`);
    }
  };

  const toggleVM = async (vmid, type, action) => {
    try {
      const endpoint = type === "qemu" ? `/vms/${vmid}/${action}` : `/lxc/${vmid}/${action}`;
      await api.post(endpoint);
      fetchVMs();
    } catch (err) {
      alert(`Failed to ${action}: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleLogout = () => {
    removeToken();
    navigate("/");
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      navigate("/");
      return;
    }
    api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    fetchVMs();
  }, []);

  return (
    <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <h2>Proxmox Cloud Dashboard</h2>
        <button onClick={handleLogout} style={{ padding: "8px 16px", backgroundColor: "#dc3545", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
          Logout
        </button>
      </div>

      <form onSubmit={createVM} style={{ marginBottom: "20px", padding: "15px", border: "1px solid #ddd", borderRadius: "8px" }}>
        <h3>Create New {vmType.toUpperCase()}</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "10px" }}>
          <input
            placeholder="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ padding: "8px" }}
            required
          />
          <select value={vmType} onChange={(e) => setVmType(e.target.value)} style={{ padding: "8px" }}>
            <option value="qemu">VM (QEMU)</option>
            <option value="lxc">LXC Container</option>
          </select>
          <input
            placeholder="OS Template"
            value={os}
            onChange={(e) => setOs(e.target.value)}
            style={{ padding: "8px" }}
          />
          <input
            type="number"
            placeholder="CPU Cores"
            value={cpu}
            onChange={(e) => setCpu(e.target.value)}
            style={{ padding: "8px" }}
            min="1"
          />
          <input
            type="number"
            placeholder="Memory (MB)"
            value={memory}
            onChange={(e) => setMemory(e.target.value)}
            style={{ padding: "8px" }}
            min="512"
          />
          <input
            type="number"
            placeholder="Disk (GB)"
            value={disk}
            onChange={(e) => setDisk(e.target.value)}
            style={{ padding: "8px" }}
            min="4"
          />
          <button type="submit" style={{ padding: "8px 16px", backgroundColor: "#007bff", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
            Create
          </button>
        </div>
      </form>

      {loading ? (
        <p>Loading...</p>
      ) : (
        <table border="1" cellPadding="10" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead style={{ backgroundColor: "#f5f5f5" }}>
            <tr>
              <th>VMID</th>
              <th>Name</th>
              <th>Type</th>
              <th>OS</th>
              <th>CPU</th>
              <th>Memory</th>
              <th>Disk</th>
              <th>IP</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {vms.length === 0 ? (
              <tr>
                <td colSpan="10" style={{ textAlign: "center", padding: "20px" }}>No VMs found</td>
              </tr>
            ) : (
              vms.map((vm) => (
                <tr key={`${vm.type}-${vm.vmid}`}>
                  <td>{vm.vmid}</td>
                  <td>{vm.name}</td>
                  <td style={{ textTransform: "uppercase" }}>{vm.type}</td>
                  <td>{vm.os}</td>
                  <td>{vm.cpu}</td>
                  <td>{vm.memory} MB</td>
                  <td>{vm.disk} GB</td>
                  <td>{vm.ip || "-"}</td>
                  <td>
                    <span style={{
                      padding: "4px 8px",
                      borderRadius: "4px",
                      backgroundColor: vm.status === "running" ? "#28a745" : vm.status === "stopped" ? "#dc3545" : "#ffc107",
                      color: "white",
                      fontSize: "12px"
                    }}>
                      {vm.status}
                    </span>
                  </td>
                  <td>
                    {vm.status !== "running" ? (
                      <button onClick={() => toggleVM(vm.vmid, vm.type, "start")} style={{ marginRight: "5px", padding: "4px 8px", backgroundColor: "#28a745", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
                        Start
                      </button>
                    ) : (
                      <button onClick={() => toggleVM(vm.vmid, vm.type, "stop")} style={{ marginRight: "5px", padding: "4px 8px", backgroundColor: "#dc3545", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
                        Stop
                      </button>
                    )}
                    <button onClick={() => deleteVM(vm.vmid, vm.type)} style={{ padding: "4px 8px", backgroundColor: "#6c757d", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
