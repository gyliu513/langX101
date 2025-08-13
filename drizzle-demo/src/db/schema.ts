import { pgTable, serial, varchar, integer, timestamp } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  name: varchar("name", { length: 50 }).notNull(),
  age: integer("age").notNull(),
  createdAt: timestamp("created_at").defaultNow(),
  role: varchar("role", { length: 20 }).default('user'),  // new column
});
