import { db } from "./db/client";
import { users } from "./db/schema";
import { eq } from "drizzle-orm";

async function main() {
  await db.insert(users).values({ name: "Charlie", age: 28 });

  const result = await db.select().from(users);
  console.log("Users:", result);

  await db.update(users).set({ age: 29 }).where(eq(users.name, "Charlie"));

  await db.delete(users).where(eq(users.name, "Charlie"));
}

main().then(() => process.exit(0));
