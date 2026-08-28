const databaseName = process.env.MONGO_DB_NAME;
const deliveryUsername = process.env.MONGO_DELIVERY_USERNAME;
const deliveryPassword = process.env.MONGO_DELIVERY_PASSWORD;
const verifierUsername = process.env.MONGO_VERIFIER_USERNAME;
const verifierPassword = process.env.MONGO_VERIFIER_PASSWORD;
const deployUsername = process.env.MONGO_DEPLOY_USERNAME;
const deployPassword = process.env.MONGO_DEPLOY_PASSWORD;

if (
  !databaseName ||
  !deliveryUsername ||
  !deliveryPassword ||
  !verifierUsername ||
  !verifierPassword ||
  !deployUsername ||
  !deployPassword
) {
  throw new Error("Mongo delivery, verifier, and deploy credentials are required");
}

const applicationDatabase = db.getSiblingDB(databaseName);
const deliveryRole = "poweradapterAuditDelivery";
const verifierRole = "poweradapterAuditVerifier";
const deployRole = "poweradapterAuditDeploy";

if (!applicationDatabase.getRole(deliveryRole)) {
  applicationDatabase.createRole({
    role: deliveryRole,
    privileges: [
      {
        resource: { db: databaseName, collection: "audit_events" },
        actions: ["find", "insert"],
      },
      {
        resource: { db: databaseName, collection: "audit_chain_heads" },
        actions: ["find", "insert", "update"],
      },
    ],
    roles: [],
  });
}

if (!applicationDatabase.getRole(verifierRole)) {
  applicationDatabase.createRole({
    role: verifierRole,
    privileges: [
      {
        resource: { db: databaseName, collection: "audit_events" },
        actions: ["find"],
      },
      {
        resource: { db: databaseName, collection: "audit_chain_heads" },
        actions: ["find"],
      },
    ],
    roles: [],
  });
}

if (!applicationDatabase.getRole(deployRole)) {
  applicationDatabase.createRole({
    role: deployRole,
    privileges: [
      {
        resource: { db: databaseName, collection: "audit_events" },
        actions: ["createCollection", "createIndex", "listIndexes"],
      },
      {
        resource: { db: databaseName, collection: "audit_chain_heads" },
        actions: ["createCollection", "createIndex", "listIndexes"],
      },
    ],
    roles: [],
  });
}

if (!applicationDatabase.getUser(deliveryUsername)) {
  applicationDatabase.createUser({
    user: deliveryUsername,
    pwd: deliveryPassword,
    roles: [{ role: deliveryRole, db: databaseName }],
  });
}

if (!applicationDatabase.getUser(verifierUsername)) {
  applicationDatabase.createUser({
    user: verifierUsername,
    pwd: verifierPassword,
    roles: [{ role: verifierRole, db: databaseName }],
  });
}

if (!applicationDatabase.getUser(deployUsername)) {
  applicationDatabase.createUser({
    user: deployUsername,
    pwd: deployPassword,
    roles: [{ role: deployRole, db: databaseName }],
  });
}
