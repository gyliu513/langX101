CREATE TABLE "users" (
	"id" serial PRIMARY KEY NOT NULL,
	"name" varchar(50) NOT NULL,
	"age" integer NOT NULL,
	"created_at" timestamp DEFAULT now()
);
