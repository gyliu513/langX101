import { db } from "./client";
import { users } from "./schema";

async function seed() {
  await db.insert(users).values([
    { name: "Alice", age: 25 },
    { name: "Bob", age: 30 },
  ]);
  console.log("✅ Seed data inserted");
}

seed().then(() => process.exit(0));
