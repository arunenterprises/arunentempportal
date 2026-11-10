export const STAFF_ROLES = ["superadmin", "admin", "hr", "manager"];
export const ROLE_LABEL = { superadmin: "SuperAdmin", admin: "Admin", hr: "HR", manager: "Manager", employee: "Employee" };
export const MODULE_LABEL = { employees: "Employees", attendance: "Attendance", requests: "Requests", leave: "Leave Balance", payslips: "Payslips", service_book: "Service Book", logins: "Login Activity" };
export const NAV_MODULE = { employees: "employees", "service-book": "service_book", attendance: "attendance", requests: "requests", payslips: "payslips", logins: "logins" };

export const isStaff = (u) => !!u && STAFF_ROLES.includes(u.role);
export const homePath = (u) => (isStaff(u) ? "/admin" : "/employee");
export const can = (u, module, action = "view") => u?.role === "superadmin" || !!u?.permissions?.[module]?.[action];
